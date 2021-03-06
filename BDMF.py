# -*- Encoding:UTF-8 -*-

import tensorflow as tf
import numpy as np
import argparse
from DataSet import DataSet
import sys
import os
import heapq
import math

os.environ['CUDA_VISIBLE_DEVICES'] = '1'

def main():
    parser = argparse.ArgumentParser(description="Options")

    parser.add_argument('-dataName', action='store', dest='dataName', default='Amusic')
    parser.add_argument('-negNum', action='store', dest='negNum', default=7, type=int)
    parser.add_argument('-userLayer', action='store', dest='userLayer', default=[512, 256])
    parser.add_argument('-itemLayer', action='store', dest='itemLayer', default=[512, 256])
    parser.add_argument('-reg', action='store', dest='reg', default=0)
    parser.add_argument('-lr', action='store', dest='lr', default=0.0001)
    parser.add_argument('-maxEpochs', action='store', dest='maxEpochs', default=50, type=int)
    parser.add_argument('-batchSize', action='store', dest='batchSize', default=256, type=int)
    parser.add_argument('-earlyStop', action='store', dest='earlyStop', default=10)
    parser.add_argument('-checkPoint_res', action='store', dest='checkPoint_res', default='./checkPoint_res/')
    parser.add_argument('-topK', action='store', dest='topK', default=10)

    args = parser.parse_args()

    classifier = Model(args)

    classifier.run()


class Model:
    def __init__(self, args):
        self.dataName = args.dataName
        self.dataSet = DataSet(self.dataName)
        self.shape = self.dataSet.shape
        self.maxRate = self.dataSet.maxRate

        self.train = self.dataSet.train
        self.test = self.dataSet.test

        self.negNum = args.negNum
        self.testNeg = self.dataSet.getTestNeg(self.test, 99)
        self.add_embedding_matrix()

        self.add_placeholders()

        self.userLayer = args.userLayer
        self.itemLayer = args.itemLayer
        self.reg = args.reg
        self.add_model()

        self.add_loss()

        self.lr = args.lr
        self.add_train_step()

        self.checkPoint_res = args.checkPoint_res
        self.init_sess()

        self.maxEpochs = args.maxEpochs
        self.batchSize = args.batchSize

        self.topK = args.topK
        self.earlyStop = args.earlyStop

    def add_placeholders(self):
        self.user = tf.placeholder(tf.int32)
        self.item = tf.placeholder(tf.int32)
        self.rate = tf.placeholder(tf.float32)
        self.drop = tf.placeholder(tf.float32)

    def add_embedding_matrix(self):
        self.user_item_embedding = tf.convert_to_tensor(self.dataSet.getEmbedding())
        self.item_user_embedding = tf.transpose(self.user_item_embedding)

    def add_model(self):
        user_input = tf.nn.embedding_lookup(self.user_item_embedding, self.user)
        item_input = tf.nn.embedding_lookup(self.item_user_embedding, self.item)

        def init_variable(shape, name):
            return tf.Variable(tf.truncated_normal(shape=shape, dtype=tf.float32, stddev=0.01), name=name)

        with tf.name_scope("User_Layer"):
            user_W1 = init_variable([self.shape[1], self.userLayer[0]], "user_W1")
            user_out = tf.matmul(user_input, user_W1)
            for i in range(0, len(self.userLayer)-1):
                W = init_variable([self.userLayer[i], self.userLayer[i+1]], "user_W"+str(i+2))
                b = init_variable([self.userLayer[i+1]], "user_b"+str(i+2))
                user_out = tf.nn.relu(tf.add(tf.matmul(user_out, W), b))
            res_user = init_variable([self.shape[1], self.userLayer[-1]], 'res_user')
            res_b = init_variable([self.userLayer[-1]], 'res_b')
            # res_b = init_variable([self.userLayer[i+1]], 'res_b')
            # Tx = tf.nn.sigmoid(tf.matmul(user_input, res_user), res_b)
            # user_out = (1-Tx) * user_input + Tx * user_out
            user_out = user_out + tf.add(tf.matmul(user_input, res_user), res_b)

        with tf.name_scope("Item_Layer"):
            item_W1 = init_variable([self.shape[0], self.itemLayer[0]], "item_W1")
            item_out = tf.matmul(item_input, item_W1)
            for i in range(0, len(self.itemLayer)-1):
                W = init_variable([self.itemLayer[i], self.itemLayer[i+1]], "item_W"+str(i+2))
                b = init_variable([self.itemLayer[i+1]], "item_b"+str(i+2))
                item_out = tf.nn.relu(tf.add(tf.matmul(item_out, W), b))
            res_item = init_variable([self.shape[0], self.itemLayer[-1]], 'res_item')
            res_b = init_variable([self.itemLayer[-1]], 'res_b')
            # res_b = init_variable([self.itemLayer[i+1]], 'res_b')
            # Tx = tf.nn.sigmoid(tf.matmul(item_input, res_item) + res_b)
            # item_out = (1-Tx) * item_input + Tx * item_out
            item_out = item_out + tf.add(tf.matmul(item_input, res_item), res_b)

        norm_user_output = tf.sqrt(tf.reduce_sum(tf.square(user_out), axis=1))
        norm_item_output = tf.sqrt(tf.reduce_sum(tf.square(item_out), axis=1))
        self.y_ = tf.reduce_sum(tf.multiply(user_out, item_out), axis=1, keep_dims=False) / (norm_item_output * norm_user_output)
        self.y_ = tf.maximum(1e-6, self.y_)

    def add_loss(self):
        regRate = self.rate / self.maxRate
        losses = regRate * tf.log(self.y_) + (1 - regRate) * tf.log(1 - self.y_)
        loss = -tf.reduce_sum(losses)
        regLoss = tf.add_n([tf.nn.l2_loss(v) for v in tf.trainable_variables()])
        self.loss = loss + self.reg * regLoss
        self.loss = loss

    def add_train_step(self):
        '''
        global_step = tf.Variable(0, name='global_step', trainable=False)
        self.lr = tf.train.exponential_decay(self.lr, global_step,
                                             self.decay_steps, self.decay_rate, staircase=True)
        '''
        optimizer = tf.train.AdamOptimizer(self.lr)
        self.train_step = optimizer.minimize(self.loss)

    def init_sess(self):
        self.config = tf.ConfigProto()
        self.config.gpu_options.allow_growth = True
        self.config.allow_soft_placement = True
        self.sess = tf.Session(config=self.config)
        self.sess.run(tf.global_variables_initializer())
        #
        # self.saver = tf.train.Saver()
        # if os.path.exists(self.checkPoint_res):
        #     [os.remove(f) for f in os.listdir(self.checkPoint_res)]
        # else:
        #     os.mkdir(self.checkPoint_res)

    def run(self):
        best_hr = -1
        best_NDCG = -1
        best_epoch = -1
        hr_list = []
        ndcg_list = []
        print("Start Training!")
        train_data = self.dataSet.getInstances(self.train, self.negNum)
        for epoch in range(self.maxEpochs):
            print("=" * 20 + "Epoch ", epoch, "=" * 20)
            self.run_epoch(self.sess, train_data)
            print('=' * 50)
            print("Start Evaluation!")
            hr, NDCG = self.evaluate(self.sess, self.topK)
            hr_list.append(hr)
            ndcg_list.append(NDCG)
            print("Epoch ", epoch, "HR: {}, NDCG: {}".format(hr, NDCG))
            # with open('BDMF_DMF_hr_ndcg.txt', 'a') as f1:
            #     f1.write('\r{} : {}'.format(round(hr, 3), round(NDCG, 3)))
            if hr > best_hr:
                best_hr = hr
                best_NDCG = NDCG
                best_epoch = epoch
                # self.saver.save(self.sess, self.checkPoint_gru)
            if epoch - best_epoch > self.earlyStop:
                print("Normal Early stop!")
                break
            print("=" * 20 + "Epoch ", epoch, "End" + "=" * 20)
        print("Best hr: {}, NDCG: {}, At Epoch {}".format(best_hr, best_NDCG, best_epoch))
        # with open('res_model_100k_hr_1layer.txt', 'a') as f:
        #     for line in hr_list:
        #         f.write(str(line))
        #         f.write('\n')
        # with open('res_model_100k_ndcg_1layer.txt', 'a') as f:
        #     for line in ndcg_list:
        #         f.write(str(line))
        #         f.write('\n')
        # print("Training complete!")

    def run_epoch(self, sess, train_data, verbose=300):
        # train_u, train_i, train_r = self.dataSet.getInstances(self.train, self.negNum)
        train_u, train_i, train_r = train_data[0], train_data[1], train_data[2]
        train_len = len(train_u)
        shuffled_idx = np.random.permutation(np.arange(train_len))
        train_u = train_u[shuffled_idx]
        train_i = train_i[shuffled_idx]
        train_r = train_r[shuffled_idx]

        num_batches = len(train_u) // self.batchSize + 1

        losses = []
        for i in range(num_batches):
            min_idx = i * self.batchSize
            max_idx = np.min([train_len, (i+1)*self.batchSize])
            train_u_batch = train_u[min_idx: max_idx]
            train_i_batch = train_i[min_idx: max_idx]
            train_r_batch = train_r[min_idx: max_idx]

            feed_dict = self.create_feed_dict(train_u_batch, train_i_batch, train_r_batch)
            _, tmp_loss = sess.run([self.train_step, self.loss], feed_dict=feed_dict)
            losses.append(tmp_loss)
            if verbose and i % verbose == 0:
                # with open('res_DMF_loss.txt','a') as f2:
                #     f2.write('\r{} : {}'.format(i, np.mean(losses[-verbose:])))
                sys.stdout.write('\r{} / {} : loss = {}'.format(
                    i, num_batches, np.mean(losses[-verbose:])
                ))
                sys.stdout.flush()
        loss = np.mean(losses)
        print("\nMean loss in this epoch is: {}".format(loss))
        return loss

    def create_feed_dict(self, u, i, r=None, drop=None):
        return {self.user: u,
                self.item: i,
                self.rate: r,
                self.drop: drop}

    def evaluate(self, sess, topK):
        def getHitRatio(ranklist, targetItem):
            for item in ranklist:
                if item == targetItem:
                    return 1
            return 0
        def getNDCG(ranklist, targetItem):
            for i in range(len(ranklist)):
                item = ranklist[i]
                if item == targetItem:
                    return math.log(2) / math.log(i+2)
            return 0


        hr =[]
        NDCG = []
        testUser = self.testNeg[0]
        testItem = self.testNeg[1]
        for i in range(len(testUser)):
            target = testItem[i][0]
            feed_dict = self.create_feed_dict(testUser[i], testItem[i])
            predict = sess.run(self.y_, feed_dict=feed_dict)

            item_score_dict = {}

            cc = len(testItem[i])
            for j in range(cc):
                j = (j+1) % cc
                item = testItem[i][j]
                item_score_dict[item] = predict[j]

            # for j in range(len(testItem[i])):
            #     item = testItem[i][j]
            #     item_score_dict[item] = predict[j]

            ranklist = heapq.nlargest(topK, item_score_dict, key=item_score_dict.get)

            tmp_hr = getHitRatio(ranklist, target)
            tmp_NDCG = getNDCG(ranklist, target)
            hr.append(tmp_hr)
            NDCG.append(tmp_NDCG)
        return np.mean(hr), np.mean(NDCG)

if __name__ == '__main__':
    main()
