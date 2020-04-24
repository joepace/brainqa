from transformers import BertModel, BertTokenizer, BertPreTrainedModel, BertConfig
from models.vqvae import VQVAE

import torch
import torch.nn as nn
from torch.nn import CrossEntropyLoss
import numpy as np

import logging

log = logging.getLogger(__name__)

class BrainQA(BertPreTrainedModel):
    def __init__(self, config):
        super(BrainQA, self).__init__(config)
        self.num_labels = config.num_labels

        # Set up BERT encoder
        self.config_enc = config.to_dict()
        self.config_enc['output_hidden_states'] = True
        self.config_enc = BertConfig.from_dict(self.config_enc)
        self.bert_enc = BertModel(self.config_enc)

        # VQVAE for external memory
        self.vqvae_model= VQVAE(h_dim=config.hidden_size, 
                                res_h_dim=32, 
                                n_res_layers=2, 
                                n_embeddings=64, 
                                embedding_dim=512, 
                                beta=.25)

        # Set up BERT decoder
        self.config_dec = config.to_dict()
        self.config_dec['is_decoder'] = True
        self.config_dec = BertConfig.from_dict(self.config_dec)
        self.bert_dec = BertModel(self.config_dec)

        # Question answer layer to output spans of question answers
        self.qa_outputs = nn.Linear(config.hidden_size, config.num_labels)
        
        self.init_weights()
    
    def forward(
        self,
        input_ids=None,
        attention_mask=None,
        token_type_ids=None,
        position_ids=None,
        head_mask=None,
        inputs_embeds=None,
        start_positions=None,
        end_positions=None,
    ):
        #B = Batch Size, S = Sequence Length, H = Hidden Size
        #outputs_encoder = (last_hidden_state: (BxSxH), pooler_output:(BxH), hidden_states: (BxSxH))
        outputs_encoder = self.bert_enc(
                input_ids,
                attention_mask=attention_mask,
                token_type_ids=token_type_ids,
                position_ids=position_ids,
                head_mask=head_mask,
                inputs_embeds=inputs_embeds,
            )
        last_hidden_state, pooler_output, hidden_states = outputs_encoder

        outputs_VQVAE = self.vqvae_model(last_hidden_state)
        vq_embedding_loss, hidden_state_reconstructed, vqvae_ppl, latent_states = outputs_VQVAE    

        log.info('Reconstructed shape: {} Latent state shape: {}'.format(hidden_state_reconstructed.shape, latent_states.shape))    

        vq_recon_loss = torch.mean((hidden_state_reconstructed - last_hidden_state)**2) # VQVAE divides this by variance of total training data 
        log.info('Recon loss: ')
        vqvae_loss = vq_recon_loss + vq_embedding_loss        
        

        # Concatenate clustered memory representations with current sentence embeddings
        vqvae_hidden_states = torch.cat((last_hidden_state, hidden_state_reconstructed), dim=1) # TODO
        
        #decoder bert
        outputs_decoder = self.bert_dec(
                input_ids,
                attention_mask=attention_mask,
                token_type_ids=token_type_ids,
                position_ids=position_ids,
                head_mask=head_mask,
                inputs_embeds=inputs_embeds,
                encoder_hidden_states = vqvae_hidden_states
            )
       
       
        sequence_output, dec_pooler_output = outputs_decoder

        logits = self.qa_outputs(sequence_output)
        start_logits, end_logits = logits.split(1, dim=-1)
        start_logits = start_logits.squeeze(-1)
        end_logits = end_logits.squeeze(-1)

        outputs = (start_logits, end_logits,) + outputs_decoder[2:]
        if start_positions is not None and end_positions is not None:
            # If we are on multi-GPU, split add a dimension
            if len(start_positions.size()) > 1:
                start_positions = start_positions.squeeze(-1)
            if len(end_positions.size()) > 1:
                end_positions = end_positions.squeeze(-1)
            # sometimes the start/end positions are outside our model inputs, we ignore these terms
            ignored_index = start_logits.size(1)
            start_positions.clamp_(0, ignored_index)
            end_positions.clamp_(0, ignored_index)

            loss_fct = CrossEntropyLoss(ignore_index=ignored_index)
            start_loss = loss_fct(start_logits, start_positions)
            end_loss = loss_fct(end_logits, end_positions)
            total_loss = (start_loss + end_loss) / 2 + vqvae_loss
            outputs = (total_loss,vqvae_loss,) + outputs
        log.info('Total Loss: {}'.format(total_loss - vqvae_loss))
        log.info('VQVAE emb_loss: {}\tppl: {}'.format(vq_embedding_loss, vqvae_ppl))
        log.info('VQVAE Loss: {}'.format(vqvae_loss))

        return outputs  # (loss), start_logits, end_logits, (hidden_states), (attentions)