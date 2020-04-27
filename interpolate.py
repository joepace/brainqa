
import argparse
import glob
import logging
import os
import random
import timeit

import numpy as np
import torch
from torch.utils.data import DataLoader, RandomSampler, SequentialSampler
from torch.utils.data.distributed import DistributedSampler
from tqdm import tqdm, trange

from transformers import (
    MODEL_FOR_QUESTION_ANSWERING_MAPPING,
    WEIGHTS_NAME,
    AdamW,
    AutoConfig,
    AutoTokenizer,
    get_linear_schedule_with_warmup,
    squad_convert_examples_to_features,
)

from transformers.data.processors.squad import SquadResult, SquadV2Processor

from models.brainqa import BrainQA
from transformers import BertModel, BertTokenizer

def run(vqvae_model):
    def generate_samples(vqvae_model, e_indices):
        #4096 is num embeddings
        min_encodings = torch.zeros(e_indices.shape[0], 4096).to(device)
        min_encodings.scatter_(1, e_indices, 1)
        e_weights = vqvae_model.vector_quantization.embedding.weight
        #z_q = torch.matmul(min_encodings, e_weights).view((params["batch_size"],8,8,params["embedding_dim"])) 
        
        #Adjusting for conv1d implementation since text not image
        #8 is batch size, 256 is embedding dim
        z_q = torch.matmul(min_encodings, e_weights).view((8,8,256))
        z_q = z_q.permute(2, 0, 1).contiguous()
    
        x_recon = vqvae_model.decoder(z_q)
        return x_recon, z_q,e_indices

    #HISTOGRAM SAMPLING
    N = 100

    e_indices = vqvae_model.e_indices

    def count_representations():
        d = {}
        for i in range(32*N):
            k = e_indices[64*i:64*i+64].squeeze().cpu().detach().numpy()
            k = [str(j)+'-' for j in k]
            k = ''.join(k)

            if k not in d:
                d[k] = 1
            else:
                d[k]+=1
        
        return d

    hist = count_representations()
    if '' in hist: del hist['']

    print('Total representations used:',len(hist.keys()))
    def sample_histogram(hist):
        keys, vals = np.array(list(hist.keys())),np.array(list(hist.values()))
        probs = np.array(vals)/sum(vals)
        #8 is batch size
        samples = np.random.choice(keys,8,p=probs,replace=True)
        
        samples = np.array([np.array([int(y) for y in x.split('-')[:-1]]) for x in samples])
        
        return samples
        
    samples = sample_histogram(hist)

    def histogram_samples(model):
        min_encoding_indices = torch.tensor(samples).reshape(-1,1).long().to(device)
        x_recon, z_q,e_indices = generate_samples(min_encoding_indices)
        
        return x_recon, z_q,e_indices

    x_hist,_,_ = histogram_samples(vqvae_model)

    display_image_grid(x_hist)