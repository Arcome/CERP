#!/usr/bin/env python
# coding: UTF-8
# based on Frederik Kratzert's alexNet with tensorflow

import os
import argparse
import sys
# import cv2
import tensorflow as tf
import numpy as np
import caffe_classes
from PIL import Image
import time
import psutil

# define different layer functions
# we usually don't do convolution and pooling on batch and channel
def maxPoolLayer(x, kHeight, kWidth, strideX, strideY, name, padding = "SAME"):
    """max-pooling"""
    return tf.nn.max_pool(x, ksize = [1, kHeight, kWidth, 1],
                          strides = [1, strideX, strideY, 1], padding = padding, name = name)

def dropout(x, keepPro, name = None):
    """dropout"""
    return tf.nn.dropout(x, keepPro, name)

def LRN(x, R, alpha, beta, name = None, bias = 1.0):
    """LRN"""
    return tf.nn.local_response_normalization(x, depth_radius = R, alpha = alpha,
                                              beta = beta, bias = bias, name = name)

def fcLayer(x, inputD, outputD, reluFlag, name):
    """fully-connect"""
    with tf.variable_scope(name) as scope:
        w = tf.get_variable("w", shape = [inputD, outputD], dtype = "float")
        b = tf.get_variable("b", [outputD], dtype = "float")
        out = tf.nn.xw_plus_b(x, w, b, name = scope.name)
        if reluFlag:
            return tf.nn.relu(out)
        else:
            return out

def convLayer(x, kHeight, kWidth, strideX, strideY,
              featureNum, name, padding = "SAME", groups = 1):
    """convolution"""
    channel = int(x.get_shape()[-1])
    conv = lambda a, b: tf.nn.conv2d(a, b, strides = [1, strideY, strideX, 1], padding = padding)
    with tf.variable_scope(name) as scope:
        w = tf.get_variable("w", shape = [kHeight, kWidth, channel/groups, featureNum])
        b = tf.get_variable("b", shape = [featureNum])

        xNew = tf.split(value = x, num_or_size_splits = groups, axis = 3)
        wNew = tf.split(value = w, num_or_size_splits = groups, axis = 3)

        featureMap = [conv(t1, t2) for t1, t2 in zip(xNew, wNew)]
        mergeFeatureMap = tf.concat(axis = 3, values = featureMap)
        # print mergeFeatureMap.shape
        out = tf.nn.bias_add(mergeFeatureMap, b)
        return tf.nn.relu(tf.reshape(out, mergeFeatureMap.get_shape().as_list()), name = scope.name)

class alexNet(object):
    """alexNet model"""
    def __init__(self, x, keepPro, classNum, skip, modelPath = "bvlc_alexnet.npy"):
        self.X = x
        self.KEEPPRO = keepPro
        self.CLASSNUM = classNum
        self.SKIP = skip
        self.MODELPATH = modelPath
        #build CNN
        self.buildCNN()

    def buildCNN(self):
        """build model"""
        conv1 = convLayer(self.X, 11, 11, 4, 4, 96, "conv1", "VALID")
        lrn1 = LRN(conv1, 2, 2e-05, 0.75, "norm1")
        pool1 = maxPoolLayer(lrn1, 3, 3, 2, 2, "pool1", "VALID")

        conv2 = convLayer(pool1, 5, 5, 1, 1, 256, "conv2", groups = 2)
        lrn2 = LRN(conv2, 2, 2e-05, 0.75, "lrn2")
        pool2 = maxPoolLayer(lrn2, 3, 3, 2, 2, "pool2", "VALID")

        conv3 = convLayer(pool2, 3, 3, 1, 1, 384, "conv3")

        conv4 = convLayer(conv3, 3, 3, 1, 1, 384, "conv4", groups = 2)

        conv5 = convLayer(conv4, 3, 3, 1, 1, 256, "conv5", groups = 2)
        pool5 = maxPoolLayer(conv5, 3, 3, 2, 2, "pool5", "VALID")

        fcIn = tf.reshape(pool5, [-1, 256 * 6 * 6])
        fc1 = fcLayer(fcIn, 256 * 6 * 6, 4096, True, "fc6")
        dropout1 = dropout(fc1, self.KEEPPRO)

        fc2 = fcLayer(dropout1, 4096, 4096, True, "fc7")
        dropout2 = dropout(fc2, self.KEEPPRO)

        self.fc3 = fcLayer(dropout2, 4096, self.CLASSNUM, True, "fc8")

    def loadModel(self, sess):
        """load model"""
        wDict = np.load(self.MODELPATH, encoding = "bytes").item()
        #for layers in model
        for name in wDict:
            if name not in self.SKIP:
                with tf.variable_scope(name, reuse = True):
                    for p in wDict[name]:
                        if len(p.shape) == 1:
                            #bias
                            sess.run(tf.get_variable('b', trainable = False).assign(p))
                        else:
                            #weights
                            sess.run(tf.get_variable('w', trainable = False).assign(p))

def main():
    os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

    imagePath = "./timerImages/"
    imageName = list(image_name for image_name in os.listdir(imagePath))
    imageNum = len(imageName)

    withPath = lambda imgName: '{}/{}'.format(imagePath,imgName)
    # testImg = dict((imgName,cv2.imread(withPath(imgName))) for imgName in imageName)
    testImg = dict((imgName,Image.open(withPath(imgName)) ) for imgName in imageName)

    # noinspection PyUnboundLocalVariable
    if testImg.values():
        #some params
        dropoutPro = 1
        classNum = 1000
        skip = []

        imgMean = np.array([104, 117, 124], np.float)
        x = tf.placeholder("float", [1, 227, 227, 3])

        model = alexnet.alexNet(x, dropoutPro, classNum, skip)
        score = model.fc3
        softmax = tf.nn.softmax(score)
        
        
        # gpu_options=tf.GPUOptions(per_process_gpu_memory_fraction=0.3)
        # config=tf.ConfigProto(gpu_options=gpu_options)
        with tf.Session() as sess:
            sess.run(tf.global_variables_initializer())
            model.loadModel(sess)
            sumTime = 0
            sumCpu = 0
            T = 100
            record_file = open("record_timer.txt", "w")
            for i in range(T):
                j = 0
                for key,img in testImg.items():
                    imgShape = np.array(img).shape
                    # print("Image size: " , imgShape)
                    #img preprocess
                    # resized = cv2.resize(img.astype(np.float), (227, 227)) - imgMean
                    resized = np.array(img.resize((227, 227))) - imgMean
                    cpu_percent = psutil.cpu_percent(interval = None)
                    sumCpu += cpu_percent
                    time0 = time.time()
                    maxx = np.argmax(sess.run(softmax, feed_dict = {x: resized.reshape((1, 227, 227, 3))}))
                    time1 = time.time()
                    sumTime += (time1 - time0)
                    # print("Image processing latency: ", time1 - time0)
                    record_file.write("{}|{}|{}|{}\n".format(i,j,cpu_percent,time1-time0))
                    res = caffe_classes.class_names[maxx]
                    j += 1
                print("i: {}|CPU: {}%|Latency: {}".format(i, cpu_percent, time1-time0), end = '\r')
                    # print("{}: {}\n----".format(key,res))
            record_file.close()
        print()
        print("Avgrage image size: {} B".format(16071))
        print("Average image processing latency: ", sumTime/(T*imageNum))
        print("Average CPU percent: ", sumCpu/(T*imageNum))

if __name__ == "__main__":
    main()