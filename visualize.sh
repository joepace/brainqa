#!/bin/bash

# Run: ./run_squad_basic.sh <outfile> to run process in background
# and redirect output to a file
# Otherwise, ./run_squad_basic.sh will run the program as usual
export SQUAD_DIR=/ml/jif24/squad

CHECKPOINT_DIR=${1:-"pretrained_v1_final/"}
python run_brainqa.py \
    --model_type bert \
    --model_name_or_path bert-base-uncased \
    --run_visualizations \
    --version_2_with_negative \
    --train_file $SQUAD_DIR/train-v2.0.json \
    --predict_file $SQUAD_DIR/dev-v2.0.json \
    --learning_rate 3e-5 \
    --num_train_epochs 4 \
    --max_seq_length 256 \
    --doc_stride 128 \
    --output_dir $CHECKPOINT_DIR \
    --eval_all_checkpoints \
    --per_gpu_eval_batch_size=2  \
    --per_gpu_train_batch_size=2   \
    --save_steps 5000 \
    --logging_steps 10
