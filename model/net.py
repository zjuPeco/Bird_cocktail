"""
 Defines the neural network, losss function and metrics
 - Largely inherited from Stanford CS230 example code:
   https://github.com/cs230-stanford/cs230-code-examples/tree/master/pytorch/vision
 - Largely borrowed from andreaazzini's repository:
   https://github.com/andreaazzini/multidensenet

"""

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim

import torchvision.models as models

import sys
import math


######################
## Helper functions ##

class Bottleneck(nn.Module):
    def __init__(self, nChannels, growthRate):
        super(Bottleneck, self).__init__()
        interChannels = 4*growthRate
        self.bn1 = nn.BatchNorm2d(nChannels)
        self.conv1 = nn.Conv2d(nChannels, interChannels, kernel_size=1,
                               bias=False)
        self.bn2 = nn.BatchNorm2d(interChannels)
        self.conv2 = nn.Conv2d(interChannels, growthRate, kernel_size=3,
                               padding=1, bias=False)

    def forward(self, x):
        out = self.conv1(F.relu(self.bn1(x)))
        out = self.conv2(F.relu(self.bn2(out)))
        out = torch.cat((x, out), 1)
        return out

class SingleLayer(nn.Module):
    def __init__(self, nChannels, growthRate):
        super(SingleLayer, self).__init__()
        self.bn1 = nn.BatchNorm2d(nChannels)
        self.conv1 = nn.Conv2d(nChannels, growthRate, kernel_size=3,
                               padding=1, bias=False)

    def forward(self, x):
        out = self.conv1(F.relu(self.bn1(x)))
        out = torch.cat((x, out), 1)
        return out

class Transition(nn.Module):
    def __init__(self, nChannels, nOutChannels):
        super(Transition, self).__init__()
        self.bn1 = nn.BatchNorm2d(nChannels)
        self.conv1 = nn.Conv2d(nChannels, nOutChannels, kernel_size=1,
                               bias=False)

    def forward(self, x):
        out = self.conv1(F.relu(self.bn1(x)))
        out = F.avg_pool2d(out, 2)
        return out


#############################
## Main Network Definition ##

class DenseNetBase(nn.Module):
    """
    Documentation for reference: http://pytorch.org/docs/master/nn.html
    """

    def __init__(self, params, num_classes):
        """
        Args:
            params: (Params) contains growthRate, depth, reduction, bottleneck
        """
        super(DenseNetBase, self).__init__()

        growthRate = params.growthRate
        depth      = params.depth
        reduction  = params.reduction
        nClasses   = num_classes
        bottleneck = True #params.bottleneck

        nDenseBlocks = (depth-4) // 3
        if bottleneck:
            nDenseBlocks //= 2

        nChannels = 2*growthRate
        self.conv1 = nn.Conv2d(1, nChannels, kernel_size=3, padding=1, bias=False)
        self.dense1 = self._make_dense(nChannels, growthRate, nDenseBlocks, bottleneck)
        nChannels += nDenseBlocks*growthRate
        nOutChannels = int(math.floor(nChannels*reduction))
        self.trans1 = Transition(nChannels, nOutChannels)

        nChannels = nOutChannels
        self.dense2 = self._make_dense(nChannels, growthRate, nDenseBlocks, bottleneck)
        nChannels += nDenseBlocks*growthRate
        nOutChannels = int(math.floor(nChannels*reduction))
        self.trans2 = Transition(nChannels, nOutChannels)

        nChannels = nOutChannels
        self.dense3 = self._make_dense(nChannels, growthRate, nDenseBlocks, bottleneck)
        nChannels += nDenseBlocks*growthRate

        self.bn1 = nn.BatchNorm2d(nChannels)
        self.fc = nn.Linear(nChannels, nClasses)

        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                n = m.kernel_size[0] * m.kernel_size[1] * m.out_channels
                m.weight.data.normal_(0, math.sqrt(2. / n))
            elif isinstance(m, nn.BatchNorm2d):
                m.weight.data.fill_(1)
                m.bias.data.zero_()
            elif isinstance(m, nn.Linear):
                m.bias.data.zero_()

    def _make_dense(self, nChannels, growthRate, nDenseBlocks, bottleneck):
        """ Construct dense layers """

        layers = []
        for i in range(int(nDenseBlocks)):
            if bottleneck:
                layers.append(Bottleneck(nChannels, growthRate))
            else:
                layers.append(SingleLayer(nChannels, growthRate))
            nChannels += growthRate

        return nn.Sequential(*layers)

    def forward(self, s):
        """
        Args:
            s: (Variable) contains a batch of images, of dimension batch_size x 128 x 192

        Returns:
            out: (Variable) dimension batch_size x num_classes with the log prob for the labels
        """       
        out = self.conv1(s)
        out = self.trans1(self.dense1(out))
        out = self.trans2(self.dense2(out))
        out = self.dense3(out)
        out = torch.squeeze(F.avg_pool2d(F.relu(self.bn1(out)), 8))
        out = out.view([out.size()[0], -1])
        return self.fc(out)


def loss_fn(outputs, labels):
    """
    Multi-label loss function
    Args:
        outputs: (Variable) 
            dimension batch_size x num_classes - output of the model
        labels: (Variable) 
            dimension batch_size x num_classes - one/multi-hot vectors

    Returns:
        loss (Variable): cross entropy loss for all images in the batch
    """

    if labels.size() != outputs.size():
        raise ValueError("Target size ({}) must be the same as input size ({})".format(labels.size(), outputs.size()))

    max_val = (-outputs).clamp(min=0)
    loss = outputs - outputs * labels + max_val + ((-max_val).exp() + (-outputs - max_val).exp()).log()
    
    return loss.mean()


def accuracy(outputs, labels):
    """
    Compute the accuracy given the outputs and labels for all images.
    Returns: (float) accuracy in [0,1]
    """
    pred = outputs.data.gt(0.5)
    tp = (pred + labels.data.byte()).eq(2).sum()
    fp = (pred - labels.data.byte()).eq(1).sum()
    fn = (pred - labels.data.byte()).eq(-1).sum()
    tn = (pred + labels.data.byte()).eq(0).sum()
    acc = (tp + tn) / (tp + tn + fp + fn)

    return acc

def precision(outputs, labels):
    """
    Compute the precision given the outputs and labels for all images.
    Returns: (float) accuracy in [0,1]
    """
    pred = outputs.data.gt(0.5)
    tp = (pred + labels.data.byte()).eq(2).sum()
    fp = (pred - labels.data.byte()).eq(1).sum()
    fn = (pred - labels.data.byte()).eq(-1).sum()
    tn = (pred + labels.data.byte()).eq(0).sum()
    acc = (tp + tn) / (tp + tn + fp + fn)
    try:
        prec = tp / (tp + fp)
    except ZeroDivisionError:
        prec = 0.0

    return prec

def recall(outputs, labels):
    """
    Compute the recall given the outputs and labels for all images.
    Returns: (float) accuracy in [0,1]
    """
    pred = outputs.data.gt(0.5)
    tp = (pred + labels.data.byte()).eq(2).sum()
    fp = (pred - labels.data.byte()).eq(1).sum()
    fn = (pred - labels.data.byte()).eq(-1).sum()
    tn = (pred + labels.data.byte()).eq(0).sum()
    acc = (tp + tn) / (tp + tn + fp + fn)
    try:
        rec = tp / (tp + fn)
    except ZeroDivisionError:
        rec = 0.0

    return rec

## metrics
metrics = {
    'accuracy' : accuracy,
    'precision': precision,
    'recall'   : recall,
}
