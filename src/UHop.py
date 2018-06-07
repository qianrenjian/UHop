import torch
import torch.nn as nn
import numpy
import math
from data_utility import PerQuestionDataset, random_split, quick_collate
from torch.utils.data import DataLoader 
import torch.nn as nn
from torch.optim import lr_scheduler
from utility import save_model, load_model 
import random
from datetime import datetime

class UHop():
    def __init__(self, args, word2id, rela2id):
        self.loss_function = nn.MarginRankingLoss(margin=args.margin)
        self.args = args
        self.word2id = word2id
        self.rela2id = rela2id
    def train_batch(self, model):
        '''
        Making batching, so cannot get acc/question
        '''
    def get_optimizer(self, model):
        if self.args.optimizer == 'adam':
            optimizer = torch.optim.Adam(params = filter(lambda p: p.requires_grad, model.parameters()), 
                    lr=self.args.learning_rate, weight_decay=self.args.l2_norm, amsgrad=True)
        if self.args.optimizer == 'rmsprop':
            optimizer = torch.optim.RMSprop(params = filter(lambda p: p.requires_grad, model.parameters()), 
                    lr=self.args.learning_rate, weight_decay=self.args.l2_norm)
        if self.args.optimizer == 'adadelta':
            optimizer = torch.optim.Adadelta(params = filter(lambda p: p.requires_grad, model.parameters()), 
                    lr=self.args.learning_rate, weight_decay=self.args.l2_norm)
        return optimizer

    def _padding(self, lists, maxlen, type, padding):
        new_lists = []
        for list in lists:
            if type == 'prepend':
                new_list = [padding] * (maxlen - len(list)) + list
            elif type == 'append':
                new_list = list + [padding] * (maxlen - len(list))
            new_lists.append(new_list)
        return new_lists

    def _single_step_rela_choose(self, model, ques, tuples):
        pos_tuples = [t for t in tuples if t[-1] == 1]
        neg_tuples = [t for t in tuples if t[-1] == 0]
        if len(pos_tuples) == 0 or len(neg_tuples) == 0:
            return 0, 1
        if len(pos_tuples) > 1:
            print('mutiple positive tuples!')
        if len(neg_tuples) > self.args.neg_sample:
            neg_tuples = neg_tuples[:self.args.neg_sample]
        pos_rela, pos_rela_text, _ = zip(*pos_tuples)
        neg_rela, neg_rela_text, _ = zip(*neg_tuples)
        maxlen = max([len(x) for x in pos_rela+neg_rela])
        pos_rela = self._padding(pos_rela, maxlen, 'prepend', self.rela2id['PADDING'])
        neg_rela = self._padding(neg_rela, maxlen, 'prepend', self.rela2id['PADDING'])
        maxlen = max([len(x) for x in pos_rela_text+neg_rela_text])
        pos_rela_text = self._padding(pos_rela_text, maxlen, 'prepend', self.word2id['PADDING'])
        neg_rela_text = self._padding(neg_rela_text, maxlen, 'prepend', self.word2id['PADDING'])
        ques = torch.LongTensor([ques]*(len(pos_rela)+len(neg_rela))).cuda()
        relas = torch.LongTensor(pos_rela+neg_rela).cuda()
        rela_texts = torch.LongTensor(pos_rela_text+neg_rela_text).cuda()
        scores = model(ques, rela_texts, relas)
        pos_scores = scores[0].repeat(len(scores)-1)
        neg_scores = scores[1:]
        ones = torch.ones(len(neg_scores)).cuda()
        loss = self.loss_function(pos_scores, neg_scores, ones)
        acc = 1 if all([x > y for x, y in zip(pos_scores, neg_scores)]) else 0
        return loss, acc

    def _termination_decision(self, model, ques, tuples, next_tuples, movement):
        if movement == 'continue':
            pos_tuples = [t for t in next_tuples if t[-1] == 1]
            neg_tuples = [t for t in tuples if t[-1] == 1]
        elif movement == 'terminate':
            pos_tuples = [t for t in tuples if t[-1] == 1]
            neg_tuples = [t for t in next_tuples if t[-1] == 0]
        else:
            raise ValueError(f'Unknown movement:{movement} in UHop._termination_decision')
        if len(pos_tuples) == 0 or len(neg_tuples) == 0:
            return 0, 1
        if len(pos_tuples) > 1:
            print('mutiple positive tuples!')
        if len(neg_tuples) > self.args.neg_sample:
            neg_tuples = neg_tuples[:self.args.neg_sample]
        pos_rela, pos_rela_text, _ = zip(*pos_tuples)
        neg_rela, neg_rela_text, _ = zip(*neg_tuples)
        maxlen = max([len(x) for x in pos_rela+neg_rela])
        pos_rela = self._padding(pos_rela, maxlen, 'prepend', self.rela2id['PADDING'])
        neg_rela = self._padding(neg_rela, maxlen, 'prepend', self.rela2id['PADDING'])
        maxlen = max([len(x) for x in pos_rela_text+neg_rela_text])
        pos_rela_text = self._padding(pos_rela_text, maxlen, 'prepend', self.word2id['PADDING'])
        neg_rela_text = self._padding(neg_rela_text, maxlen, 'prepend', self.word2id['PADDING'])
        ques = torch.LongTensor([ques]*(len(pos_rela)+len(neg_rela))).cuda()
        relas = torch.LongTensor(pos_rela+neg_rela).cuda()
        rela_texts = torch.LongTensor(pos_rela_text+neg_rela_text).cuda()
        scores = model(ques, rela_texts, relas)
        pos_scores = scores[0].repeat(len(scores)-1)
        neg_scores = scores[1:]
        ones = torch.ones(len(neg_scores)).cuda()
        loss = self.loss_function(pos_scores, neg_scores, ones)
        acc = 1 if all([x > y for x, y in zip(pos_scores, neg_scores)]) else 0
        return loss, acc

    def train(self, model):
        '''
        train 1 batch / question
        '''
        dataset = PerQuestionDataset(self.args, 'train', self.word2id, self.rela2id)
        if self.args.dataset.lower() == 'wq' or self.args.dataset.lower() == 'wq_train1test2':
            train_dataset, valid_dataset = random_split(dataset, 0.9, 0.1)
        else:
            train_dataset = dataset
            valid_dataset = PerQuestionDataset(self.args, 'valid', self.word2id, self.rela2id)
        datas = DataLoader(dataset=train_dataset, batch_size=1, shuffle=True, num_workers=0, 
                pin_memory=False, collate_fn=quick_collate)
        optimizer = self.get_optimizer(model)
        earlystop_counter, min_valid_metric = 0, 100
        for epoch in range(0, self.args.epoch_num):
            model = model.train().cuda()
            total_loss, total_acc, total_rc_acc, total_td_acc = 0.0, 0.0, 0.0, 0.0
            loss_count, acc_count, rc_count, td_count = 0, 0, 0, 0
            for trained_num, (_, ques, step_list) in enumerate(datas):
                acc_list = []
                for i in range(len(step_list)-1):
                    optimizer.zero_grad();model.zero_grad(); 
                    loss, acc = self._single_step_rela_choose(model, ques, step_list[i])
                    if loss != 0:
                        loss.backward(); optimizer.step()
                        total_loss += loss.data; loss_count += 1
                    else:
                        loss_count += 1
                    acc_list.append(acc)
                    total_rc_acc += acc; rc_count += 1
                    if self.args.stop_when_err and acc != 1:
                        break
                    if i + 2 < len(step_list):
                        # do continue
                        optimizer.zero_grad();model.zero_grad(); 
                        loss, acc = self._termination_decision(model, ques, step_list[i], step_list[i+1], 'continue')
                        if loss != 0:
                            loss.backward(); optimizer.step()
                            total_loss += loss.data; loss_count += 1
                        else:
                            loss_count += 1
                        acc_list.append(acc)
                        total_td_acc += acc; td_count += 1
                optimizer.zero_grad();model.zero_grad()
                loss, acc = self._termination_decision(model, ques, step_list[i], step_list[i+1], 'terminate')
                if loss != 0:
                    loss.backward(); optimizer.step()
                    total_loss += loss.data; loss_count += 1
                else:
                    loss_count += 1
                acc_list.append(acc)
                total_td_acc += acc; td_count += 1
                acc = 1 if all([x == 1 for x in acc_list]) else 0
                total_acc += acc; acc_count += 1
                print(f'\r{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} Epoch {epoch} {trained_num}/{len(datas)} Loss:{total_loss/loss_count:.5f} Acc:{total_acc/acc_count:.4f} RC_Acc:{total_rc_acc/rc_count:.2f} TD_Acc:{total_td_acc/td_count:.2f}', end='')
            _, valid_loss, valid_acc = self.eval(model, 'valid', valid_dataset)
            if valid_loss < min_valid_metric:
                min_valid_metric = valid_loss
                earlystop_counter = 0
                save_model(model, self.args.path)
            else:
                earlystop_counter += 1
            if earlystop_counter > self.args.earlystop_tolerance:
                break       
        return model, total_loss / loss_count, total_acc / acc_count
            

    def eval(self, model, mode, dataset):
        '''
        For test and validation
        mode: valid | test
        '''
        if model == None:
            import_model_str = 'from model.{} import Model as Model'.format(self.args.model)
            model = self.args.Model(self.args).cuda()
            model = load_model(model, self.args.path)
        model = model.eval().cuda()
        if dataset == None:
            dataset = PerQuestionDataset(self.args, mode, self.word2id, self.rela2id)
        datas = DataLoader(dataset=dataset, batch_size=1, shuffle=False, num_workers=0, 
                pin_memory=False, collate_fn=quick_collate)
        total_loss, total_acc, total_rc_acc, total_td_acc = 0.0, 0.0, 0.0, 0.0
        loss_count, acc_count, rc_count, td_count = 0, 0, 0, 0
        for num, (_, ques, step_list) in enumerate(datas):
            acc_list = []
            for i in range(len(step_list)-1):
                loss, acc = self._single_step_rela_choose(model, ques, step_list[i])
                acc_list.append(acc)
                if loss != 0:
                    total_loss += loss.data; loss_count += 1
                else:
                    loss_count += 1
                total_rc_acc += acc; rc_count += 1
                if self.args.stop_when_err and acc != 1:
                    break
                if i + 2 < len(step_list):
                    # do continue
                    loss, acc = self._termination_decision(model, ques, step_list[i], step_list[i+1], 'continue')
                    acc_list.append(acc)
                    if loss != 0:
                        total_loss += loss.data; loss_count += 1
                    else:
                        loss_count += 1
                        total_td_acc += acc; td_count += 1
            loss, acc = self._termination_decision(model, ques, step_list[i], step_list[i+1], 'terminate')
            acc_list.append(acc)
            if loss != 0:
                total_loss += loss.data; loss_count += 1
            else:
                loss_count += 1
                total_td_acc += acc; td_count += 1
            total_td_acc += acc; td_count += 1
            acc = 1 if all(acc_list) else 0
            total_acc += acc; acc_count += 1
        print(f' Eval {num} Loss:{total_loss/loss_count:.5f} Acc:{total_acc/acc_count:.4f} RC_Acc:{total_rc_acc/rc_count:.2f} TD_Acc:{total_td_acc/td_count:.2f}', end='')
        print('')
        return model, total_loss / loss_count, total_acc / acc_count