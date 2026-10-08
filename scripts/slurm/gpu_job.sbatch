#!/bin/bash
#SBATCH --job-name=minpilot_gpu
#SBATCH --partition=main
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x-%j.out
# Generic GPU job wrapper: sbatch [--job-name=X --time=...] scripts/slurm/gpu_job.sbatch <command> [args...]
# Override any #SBATCH default on the sbatch command line. Submit from the repo root (logs/ must exist).

set -o pipefail   # -e/-u only after conda activation: `conda activate` aborts under set -e (bash 5.2)

source /home/compu/anaconda3/etc/profile.d/conda.sh
conda activate "${CONDA_ENV:-doh_base}"
set -eu

export PYTHONUNBUFFERED=1
export HF_HOME=/data2/dohyun/hf

cd "$SLURM_SUBMIT_DIR"
echo "job=$SLURM_JOB_ID node=$(hostname) gpus=$CUDA_VISIBLE_DEVICES env=${CONDA_ENV:-doh_base}"
echo "cmd: $*"

"$@"
