import os
import os.path as osp
import pickle
import csv
import collections

import numpy as np
import PIL.Image as Image
from numpy.core.fromnumeric import sort
import torch
from torch.utils.data import Dataset
from torchvision import transforms
from torchvision.transforms import Compose, Normalize, Resize, ToTensor
import json

class DataSet(Dataset):

    def __init__(self, data_root, setname, img_size):
        self.img_size = img_size
        if setname in ["test", "novel_all", "val"]:
            json_path = osp.join(data_root, setname + '.json') # 当测试数据集与源数据集不一致时使用
        elif setname == "train":
            json_path = osp.join(data_root, 'base.json')
        with open(json_path, "r") as f:
            self.meta = json.load(f) # json file(dict) ： {"label_names:[...], "image_names":[...], "image_labels":[...]}

        data = self.meta["image_names"]
        label = self.meta["image_labels"] # dataset 返回的label并无实际作用,只是当做一个类别标识

        self.data = data  # data path of all data
        self.label = label  # label of all data
        self.num_class = len(set(label))
        self.wnids = self.meta["label_names"]

        if setname=='test' or setname=='val':
            self.transform = transforms.Compose([
                                               transforms.Resize((img_size, img_size)),
                                               transforms.ToTensor(),
                                               transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
                                       ])
        else:
            self.transform = transforms.Compose([
                                            transforms.RandomResizedCrop((img_size, img_size)),
                                            transforms.RandomHorizontalFlip(),
                                            transforms.ToTensor(),
                                            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
                                        ])
            
    def __len__(self):
        return len(self.data)

    def __getitem__(self, i):
        if i == -1:
            return torch.zeros([3, self.img_size, self.img_size]), 0
        path, label = self.data[i], self.label[i]
        image = self.transform(Image.open(path).convert('RGB'))
        return image, 1


class CategoriesSampler():

    def __init__(self, label, n_batch, n_cls, n_per):
        self.n_batch = n_batch #num_batches
        self.n_cls = n_cls # test_ways
        self.n_per = np.sum(n_per) # num_per_class
        self.number_distract = n_per[-1]

        label = np.array(label)
        self.m_ind = []
        for i in range(max(label) + 1):
            ind = np.argwhere(label == i).reshape(-1)
            ind = torch.from_numpy(ind)
            self.m_ind.append(ind)

    def __len__(self):
        return self.n_batch
    
    def __iter__(self):
        for i_batch in range(self.n_batch):
            batch = []
            indicator_batch = []
            classes = torch.randperm(len(self.m_ind))
            trad_classes = classes[:self.n_cls]
            for c in trad_classes:
                l = self.m_ind[c]
                pos = torch.randperm(len(l))[:self.n_per]
                cls_batch = l[pos]
                cls_indicator = np.zeros(self.n_per)
                cls_indicator[:cls_batch.shape[0]] = 1
                if cls_batch.shape[0] != self.n_per:
                    cls_batch = torch.cat([cls_batch, -1*torch.ones([self.n_per-cls_batch.shape[0]]).long()], 0)
                batch.append(cls_batch)
                indicator_batch.append(cls_indicator)
            batch = torch.stack(batch).t().reshape(-1)
            yield batch


filenameToPILImage = lambda x: Image.open(x).convert('RGB')

def loadSplit(splitFile):
    dictLabels = {}
    with open(splitFile) as csvfile:
        csvreader = csv.reader(csvfile, delimiter=',')
        next(csvreader, None)
        for i,row in enumerate(csvreader):
            filename = row[0]
            label = row[1]
            if label in dictLabels.keys():
                dictLabels[label].append(filename)
            else:
                dictLabels[label] = [filename]
    return dictLabels

def loadSplitFromJson(splitFile):
    dictLabels = {}
    with open(splitFile) as f:
        meta = json.load(f)
        for filename, j in zip(meta["image_names"], meta["image_labels"]):
            label = meta["label_names"][j]
            if label in dictLabels.keys():
                dictLabels[label].append(filename)
            else:
                dictLabels[label] = [filename]
    return dictLabels


class EmbeddingDataset(Dataset):

    def __init__(self, dataroot, img_size, type = 'train'):
        self.img_size = img_size
        # Transformations to the image
        if type=='train':
            self.transform = transforms.Compose([filenameToPILImage,
                                                transforms.Resize((img_size, img_size)),
                                                transforms.RandomCrop(img_size, padding=8),
                                                transforms.ColorJitter(brightness=0.4, contrast=0.4, saturation=0.4),
                                                transforms.RandomHorizontalFlip(),
                                                transforms.ToTensor(),
                                                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
                                                ])
        else:
            self.transform = transforms.Compose([filenameToPILImage,
                                                transforms.Resize((img_size, img_size)),
                                                transforms.ToTensor(),
                                                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
                                                ])

        
        self.ImagesDir = os.path.join(dataroot,'images')
        # self.data = loadSplit(splitFile = os.path.join(dataroot,'train' + '.csv'))
        self.data = loadSplitFromJson(splitFile = os.path.join(dataroot,'base' + '.json'))
        for i,j in self.data.items():
            j.sort()
        self.data = collections.OrderedDict(sorted(self.data.items()))
        keys = list(self.data.keys())
        self.classes_dict = {keys[i]:i  for i in range(len(keys))} # map NLabel to id(0-99)

        self.Files = []
        self.belong = []

        for c in range(len(keys)):
            num = 0
            num_train = int(len(self.data[keys[c]]) * 9 / 10)
            for file in self.data[keys[c]]:
                if type == 'train' and num <= num_train:
                    self.Files.append(file)
                    self.belong.append(c)
                elif type=='val' and num>num_train:
                    self.Files.append(file)
                    self.belong.append(c)
                num = num+1


        self.__size = len(self.Files)

    def __getitem__(self, index):

        c = self.belong[index]
        File = self.Files[index]

        # path = os.path.join(self.ImagesDir,str(File))
        path = str(File)
        try:
            images = self.transform(path)
        except RuntimeError:
            import pdb;pdb.set_trace()
        return images,c

    def __len__(self):
        return self.__size

