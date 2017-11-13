import math
import torch
import torch.nn as nn
import torch.nn.init as init
from torch.autograd import Variable

def init_weights(modules):
    for m in modules():
        if isinstance(m, nn.Conv2d):
            nn.init.kaiming_normal(m.weight, mode="fan_out")


class MeanShift(nn.Module):
    def __init__(self, mean_rgb, sub):
        super(MeanShift, self).__init__()

        sign = -1 if sub else 1
        r = mean_rgb[0] * sign
        g = mean_rgb[1] * sign
        b = mean_rgb[2] * sign

        self.shifter = nn.Conv2d(3, 3, 1, 1, 0)
        self.shifter.weight.data = torch.eye(3).view(3, 3, 1, 1)
        self.shifter.bias.data   = torch.Tensor([r, g, b])

        # Freeze the mean shift layer
        for params in self.shifter.parameters():
            params.requires_grad = False

    def forward(self, x):
        x = self.shifter(x)
        return x


class BasicBlock(nn.Module):
    def __init__(self, 
                 in_channels, out_channels,
                 dilation=1, 
                 act=nn.ReLU()):
        super(BasicBlock, self).__init__()

        # assume input.shape == output.shape
        pad = dilation

        self.body = nn.Sequential(
            nn.Conv2d(in_channels, out_channels, 3, 1, pad, dilation=dilation, bias=False),
            act
        )

        init_weights(self.modules)
        
    def forward(self, x):
        out = self.body(x)
        return out


class MDBlock(nn.Module):
    def __init__(self, 
                 in_channels, out_channels,
                 dilation=[2, 4],
                 act=nn.ReLU()):
        super(MDBlock, self).__init__()

        self.branch0 = BasicBlock(in_channels, int(out_channels/2), dilation[0], act)
        self.branch1 = BasicBlock(in_channels, int(out_channels/2), dilation[1], act)

        self.exit = nn.Sequential(
            nn.Conv2d(out_channels, out_channels, 1, 1, 0, bias=False),
            act
        )
        
        init_weights(self.modules)

    def forward(self, x):
        branch0 = self.branch0(x)
        branch1 = self.branch1(x)

        out = torch.cat((branch0, branch1), dim=1)
        out = self.exit(out)
        return out


class ResidualBlock(nn.Module):
    def __init__(self, 
                 in_channels, out_channels,
                 dilation=1, 
                 act=nn.ReLU()):
        super(ResidualBlock, self).__init__()

        # assume input.shape == output.shape
        pad = dilation

        self.body = nn.Sequential(
            nn.Conv2d(in_channels, out_channels, 3, 1, pad, dilation=dilation, bias=False),
            act,
            nn.Conv2d(out_channels, out_channels, 3, 1, pad, dilation=dilation, bias=False),
        )

        if not in_channels == out_channels:
            self.identity = nn.Conv2d(in_channels, out_channels, 1, 1, 0, bias=False)

        self.act = act

        init_weights(self.modules)
        
    def forward(self, x):
        out = self.body(x)
        if getattr(self, "identity", None):
            x = self.identity(x)
        out = self.act(out + x)
        return out
        
        
class MDRBlockA(nn.Module):
    def __init__(self, 
                 in_channels, out_channels,
                 dilation=[2, 4],
                 act=nn.ReLU()):
        super(MDRBlockA, self).__init__()
        
        self.branch0 = ResidualBlock(in_channels, int(out_channels/2), dilation[0], act)
        self.branch1 = ResidualBlock(in_channels, int(out_channels/2), dilation[1], act)

        self.exit = nn.Sequential(
            nn.Conv2d(out_channels, out_channels, 1, 1, 0, bias=False),
            act
        )
        
        init_weights(self.modules)

    def forward(self, x):
        branch0 = self.branch0(x)
        branch1 = self.branch1(x)

        out = torch.cat((branch0, branch1), dim=1)
        out = self.exit(out) + x
        return out
        
        
class MDRBlockB(nn.Module):
    def __init__(self, 
                 in_channels, reduce_channels, out_channels,
                 dilation=[2, 4],
                 act=nn.ReLU()):
        super(MDRBlockB, self).__init__()
        
        self.branch1 = nn.Sequential(
            nn.Conv2d(in_channels, reduce_channels, 1, 1, 0, bias=False),
            act,
            ResidualBlock(reduce_channels, reduce_channels, dilation[0], act)
        )
        self.branch2 = nn.Sequential(
            nn.Conv2d(in_channels, reduce_channels, 1, 1, 0, bias=False),
            act,
            ResidualBlock(reduce_channels, reduce_channels, dilation[1], act)
        )

        self.exit = nn.Sequential(
            nn.Conv2d(reduce_channels*2, out_channels, 1, 1, 0, bias=False),
            act
        )
        
        # init_weights(self.modules)

    def forward(self, x):
        branch1 = self.branch1(x)
        branch2 = self.branch2(x)

        out = torch.cat((branch1, branch2), dim=1)
        out = self.exit(out) + x
        return out

 
class UpsampleBlock(nn.Module):
    def __init__(self, n_channels, scale, act=False):
        super(UpsampleBlock, self).__init__()

        modules = []
        if scale == 2 or scale == 4 or scale == 8:
            for _ in range(int(math.log(scale, 2))):
                modules += [nn.Conv2d(n_channels, 4*n_channels, 3, 1, 1)]
                modules += [nn.PixelShuffle(2)]
                if act:
                    modules += [act]
        elif scale == 3:
            modules += [nn.Conv2d(n_channels, 9*n_channels, 3, 1, 1)]
            modules += [nn.PixelShuffle(3)]
            if act:
                modules += [act]
        self.body = nn.Sequential(*modules)

        init_weights(self.modules)
        
    def forward(self, x):
        out = self.body(x)
        return out