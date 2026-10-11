Last modified: May 19, 2026 (Hoyeon Chang)

# Slurm User Guide

A technical guide for users who want to run jobs on the lab cluster. This document assumes you have already read **What is Slurm?**

If you are reading this in order to install or configure Slurm itself, see the **Slurm Setup Guide (for admin)** instead.

---

## 0. Current cluster status

| Feature | Status |
| --- | --- |
| Basic CPU/memory scheduling (`srun`, `sbatch`, `salloc`) | Active |
| GPU allocation (`--gres=gpu:N`) | Active |
| Strict memory enforcement (cgroup) | Active |
| Job accounting (`sacct`) | Active |
| Direct SSH to compute nodes (for non-GPU work) | Allowed |
| GPU use outside Slurm | Soft-blocked (see §9) |
| Job time limit | 24 hours maximum, 2 hours default |
| Scheduling | Fair-share priority (heavy recent users wait longer) |
| `/scratch` and `/home` layout | Default paths; planned layout not yet applied |

The cluster currently has one node (`gpu01`) with two NVIDIA RTX PRO 6000 Blackwell GPUs. Two more are being added.

---

## 1. Quick start

A working "hello world" in 60 seconds. Paste the following into your terminal after SSHing into the cluster:

```bash
cat > hello.sh <<'EOF'
#!/bin/bash
#SBATCH --job-name=hello
#SBATCH --output=hello-%j.out
#SBATCH --time=00:01:00
#SBATCH --mem=1G

echo "Hello from $(hostname), job ID $SLURM_JOB_ID"
sleep 5
echo "Done"
EOF

sbatch hello.sh
```

You should see something like:

```
Submitted batch job 42
```

That number is your **job ID**. Check whether it is still in the queue:

```bash
squeue -u $USER
```

You should see one row with your job, with state `R` (running) or `PD` (pending). After about 5 seconds it disappears from the queue, meaning it has completed. Read the output:

```bash
cat hello-42.out
```

Expected:

```
Hello from gpu01, job ID 42
Done
```

That is one full Slurm cycle: submit, observe in queue, run, capture output.

---

## 2. The three submission commands

### `sbatch`: submit a script to run later

Your default. You write a shell script, put `#SBATCH` directives at the top to declare resources, and submit it.

```bash
sbatch my_job.sh
```

Slurm queues the job, returns immediately, and runs the script when resources are available. You do not need to stay logged in.

Use `sbatch` for training runs, data preprocessing, evaluation, or anything that takes more than a couple of minutes.

### `srun`: run a command directly

`srun` runs a command synchronously inside a Slurm allocation. Your terminal waits for it to finish.

```bash
srun --mem=4G --time=00:10:00 python quick_test.py
```

Use `srun` for:

- Quick one-off tests
- Running things you want to watch live
- Interactive debugging (with `-pty bash`)
- Multiple parallel steps within an `sbatch` script (advanced)

The `--pty bash` form is the recommended way to get an interactive shell with allocated resources:

```bash
srun --gres=gpu:1 --mem=16G --time=2:00:00 --pty bash
# now in a shell on the compute node, with the GPU allocated
nvidia-smi -L            # shows only the GPU you asked for
python train.py
exit                     # ends the job and frees resources
```

Inside this shell, `CUDA_VISIBLE_DEVICES` is set, the GPU is visible, and CUDA code runs normally.

### `salloc`: reserve resources for repeated use

`salloc` reserves resources but does not by itself put your shell inside the job's resource limits. You stay in your original SSH shell, with the allocation set aside. To actually run something inside the allocation, you launch it with `srun`:

```bash
salloc --gres=gpu:1 --mem=16G --time=2:00:00
# allocation is now reserved; same shell as before

srun python test1.py     # runs inside the allocation, sees the GPU
srun python test2.py     # reuses the same allocation, no queue wait
srun --pty bash          # interactive shell inside the allocation

exit                     # releases the allocation
```

Commands run directly in the `salloc` shell (without `srun`) do not get the GPU and do not see the cgroup limits. They run with the same environment as a regular SSH session.

Use `salloc` when you want to keep an allocation alive across many short commands without re-queuing each time.

### When to use which

- `sbatch` for unattended work. Most of your usage.
- `srun --pty bash` for an interactive session with allocated resources. This is what you want most of the time when working interactively.
- `srun <command>` for short attached commands, and inside `sbatch` scripts when you need finer-grained task control.
- `salloc` for advanced cases where you want to hold a reservation across multiple `srun` calls.

---

## 3. Monitoring and controlling jobs

Beyond `squeue -u $USER`, a few commands you will use often.

### `squeue`: what is in the queue

```bash
squeue                  # all jobs
squeue -u $USER         # just yours
squeue -j 1234          # a specific job
squeue --start          # estimated start times for pending jobs
```

Output columns:

- `JOBID`: job ID
- `PARTITION`: queue it is in
- `NAME`: `-job-name`
- `USER`: owner
- `ST`: state code
- `TIME`: elapsed runtime
- `NODES` / `NODELIST(REASON)`: where it is running, or why it is pending

Common state codes:

| Code | Meaning |
| --- | --- |
| `R` | Running |
| `PD` | Pending (waiting) |
| `CG` | Completing (cleanup phase) |
| `CD` | Completed |
| `F` | Failed |
| `CA` | Cancelled |
| `TO` | Timeout (hit `--time` limit) |
| `OOM` | Out of memory (killed) |

Common pending reasons:

| Reason | Meaning |
| --- | --- |
| `Resources` | Waiting for nodes to free up |
| `Priority` | Other jobs ahead in queue |
| `QOSMaxJobs` | You hit a per-user limit |
| `Dependency` | Waiting for another job to finish |
| `ReqNodeNotAvail` | A requested node is down |

### `scontrol show job <id>`: full details

```bash
scontrol show job 1234
```

Shows everything: exact resource allocation, start time, working directory, stdout path, full command. Useful when a job behaves unexpectedly.

### `scancel`: stop jobs

```bash
scancel 1234                # one job
scancel -u $USER            # all your jobs
scancel --name=train_resnet # by job name
scancel --state=PD -u $USER # all your pending jobs
```

### `sacct`: historical job information

```bash
sacct                                                       # your recent jobs
sacct -j 1234                                               # specific job
sacct --starttime 2026-05-01                                # since a date
sacct --format=JobID,JobName,State,Elapsed,MaxRSS,ReqMem,AllocTRES%40,ExitCode
```

`MaxRSS` is the maximum memory your job actually used. Use it to right-size `--mem` for future submissions.

`AllocTRES` shows the resources actually allocated, including `gres/gpu=N` for GPU jobs. Useful when verifying that GPUs were assigned as requested.

### Modify a pending job

Only some attributes are modifiable, and only before the job starts running.

```bash
scontrol update JobId=1234 TimeLimit=48:00:00
scontrol update JobId=1234 Partition=long
```

Most parameters cannot be changed after submission. If you got it wrong, cancel and resubmit.

### Hold and release

```bash
scontrol hold 1234     # block a pending job from starting
scontrol release 1234  # allow it to start
```

### Watching output in real time

```bash
tail -f logs/train_resnet-1234.out
```

stdout from a Slurm job is flushed less aggressively than when you run interactively. If output looks stuck, the Python process probably has not flushed its buffers. Use `python -u`, add `flush=True` to print calls, or set `PYTHONUNBUFFERED=1` in the environment.

---

## 4. Anatomy of an `sbatch` script

```bash
#!/bin/bash
#SBATCH --job-name=train_resnet         # appears in `squeue`
#SBATCH --partition=main                # which queue
#SBATCH --nodes=1                       # how many machines
#SBATCH --ntasks=1                      # how many parallel tasks
#SBATCH --cpus-per-task=8               # CPU cores per task
#SBATCH --mem=64G                       # memory per node
#SBATCH --gres=gpu:1                    # GPU count
#SBATCH --time=12:00:00                 # max wall time HH:MM:SS
#SBATCH --output=logs/%x-%j.out         # stdout, %x=name %j=jobid
#SBATCH --error=logs/%x-%j.err          # stderr (omit to merge with stdout)

# Everything below is normal shell, running on a compute node with the
# resources above allocated to it.

source /home/compu/anaconda3/etc/profile.d/conda.sh
conda activate myenv

cd ~/projects/resnet
python train.py --config configs/default.yaml
```

The `#SBATCH` lines are comments to bash but directives to Slurm. They must appear before any executable line, with no blank lines in between. Once Slurm sees the first non-comment line, it stops parsing directives.

Every flag has a long form (`--job-name`) and a short form (`-J`). Long forms are preferred in scripts for readability.

### Most-used directives

| Directive | What it does | Example |
| --- | --- | --- |
| `--job-name` | Name shown in queue | `--job-name=train` |
| `--partition` | Which queue to submit to | `--partition=main` |
| `--time` | Maximum wall time (job killed if it runs longer) | `--time=24:00:00` |
| `--mem` | Memory per node | `--mem=64G` |
| `--cpus-per-task` | CPU cores per task | `--cpus-per-task=8` |
| `--ntasks` | Number of parallel tasks (use for MPI) | `--ntasks=4` |
| `--nodes` | Number of nodes | `--nodes=1` |
| `--gres=gpu:N` | Number of GPUs | `--gres=gpu:2` |
| `--output` | Where stdout goes | `--output=logs/%x-%j.out` |
| `--error` | Where stderr goes (omit to merge with stdout) | `--error=logs/%x-%j.err` |
| `--mail-type` | When to email (BEGIN, END, FAIL, ALL) | `--mail-type=END,FAIL` |
| `--mail-user` | Where to email | `--mail-user=you@example.com` |
| `--dependency` | Wait for another job | `--dependency=afterok:12345` |
| `--array` | Submit many jobs in one go (see §7) | `--array=0-9` |

### Filename patterns

In `--output` and `--error`:

- `%j`: job ID
- `%x`: job name
- `%a`: array task ID (for job arrays)
- `%N`: node name
- `%u`: username

Example: `--output=logs/%x-%j.out` produces files like `logs/train_resnet-1234.out`.

**Important.** Create the `logs/` directory before submitting. Slurm will not create it for you, and the job will fail to write output.

### Required directives for any real job

For every job that is not a throwaway test:

- `-job-name` so you can identify it in `squeue`
- `-time` so the backfill scheduler can place your job efficiently
- `-mem` matching what you actually need with a small buffer
- `-cpus-per-task` if you use more than 1
- `-output` to a logs directory you have created

### Time limits

Jobs have a hard ceiling of **24 hours**. Requests longer than that are rejected at submission. If you omit `--time`, the job receives a default of **2 hours**.

If your work needs to run longer than 24 hours, use checkpointing and chain restarts (§7.4). The cluster intentionally has no "long" partition; this keeps the scheduler responsive for everyone.

---

## 5. Specifying GPUs

GPUs are requested via the **GRES** (Generic Resource) mechanism. Slurm treats GPUs as a typed, countable resource you reserve.

### Request one GPU

```bash
#SBATCH --gres=gpu:1
```

Inside the job, `nvidia-smi` will show only one GPU even if the node has more. `CUDA_VISIBLE_DEVICES` will be set automatically. Most ML frameworks pick it up without any code change.

### Request multiple GPUs

```bash
#SBATCH --gres=gpu:4
```

For multi-GPU training (PyTorch DDP), match CPUs and memory:

```bash
#SBATCH --gres=gpu:4
#SBATCH --cpus-per-task=32
#SBATCH --mem=256G
```

### Request a specific GPU type

```bash
#SBATCH --gres=gpu:rtx6000:2
```

Useful once the cluster has heterogeneous nodes. Currently all GPUs in this cluster are the same model.

### Verify what you got

Inside the job:

```bash
echo "Allocated GPUs: $CUDA_VISIBLE_DEVICES"
nvidia-smi --query-gpu=index,name,memory.total --format=csv
```

---

## 6. Environment integration

### 6.1 Conda (recommended for most workflows)

The cluster has a shared conda installation under the admin account. Regular users source it and create their own environments, which are stored under each user's home directory. The base environment is read-only to regular users.

### Initial setup (once per user)

Add the following to the end of your `~/.bashrc`:

```bash
# conda
export PATH="/home/compu/anaconda3/bin:$PATH"
export CONDA_ENVS_PATH="$HOME/.conda/envs"
export CONDA_PKGS_DIRS="$HOME/.conda/pkgs"

# initialize conda
source /home/compu/anaconda3/etc/profile.d/conda.sh
```

`CONDA_ENVS_PATH` and `CONDA_PKGS_DIRS` ensure your environments and package cache go under your own home directory rather than being attempted in the shared installation (which is read-only to you).

Reload and verify:

```bash
source ~/.bashrc
which conda
# expect: /home/compu/anaconda3/bin/conda
```

Keep conda environments in your home directory, not on the NAS (once it is set up). Conda installations contain many small files that perform poorly over network storage.

### Inside a job script

```bash
#!/bin/bash
#SBATCH --job-name=train
#SBATCH --time=4:00:00
#SBATCH --mem=32G
#SBATCH --gres=gpu:1

# Source the cluster's conda installation explicitly.
# Slurm jobs do not source ~/.bashrc, so the PATH and conda init
# from your interactive setup are not in effect here.
source /home/compu/anaconda3/etc/profile.d/conda.sh

# Activate your own environment.
conda activate myenv

python train.py
```

### Why `source` is necessary

Slurm jobs run in non-interactive, non-login shells. Your `~/.bashrc` is not sourced, so the `conda init` block does not execute and `conda` is not on PATH. Sourcing `conda.sh` directly fixes this.

If you use mamba or micromamba on top of the same installation:

```bash
source /home/compu/anaconda3/etc/profile.d/mamba.sh
mamba activate myenv
```

### Creating your own environment

The base environment is read-only. Create your own:

```bash
conda create -n myenv python=3.11
conda activate myenv
pip install torch torchvision
```

Packages are stored under your home directory (`$CONDA_ENVS_PATH`), not in the shared conda installation. You cannot affect other users' environments.

### Sharing environments

To export the package list:

```bash
conda env export --from-history > environment.yml
```

To recreate elsewhere:

```bash
conda env create -f environment.yml
```

- `-from-history` produces a minimal file listing only the packages you explicitly installed. Without it, the file pins every transitive dependency to its current version, which often fails to resolve on a different machine.

### 6.2 Containers (Apptainer)

Apptainer (formerly Singularity) is the standard container runtime for HPC clusters. It runs without root and integrates with Slurm without extra configuration.

> Apptainer may not yet be installed on this cluster. Confirm with the admin before relying on it.
> 

### Using a Docker image with Apptainer

Pull and convert in one step:

```bash
apptainer pull pytorch.sif docker://pytorch/pytorch:2.1.0-cuda12.1-cudnn8-runtime
```

Run a command inside it:

```bash
apptainer exec --nv pytorch.sif python train.py
```

The `--nv` flag forwards the host's NVIDIA drivers so CUDA works inside the container.

### Inside a job script

```bash
#!/bin/bash
#SBATCH --job-name=container_run
#SBATCH --time=4:00:00
#SBATCH --mem=32G
#SBATCH --gres=gpu:1

apptainer exec --nv \
    --bind $PWD:/workspace \
    pytorch.sif \
    python /workspace/train.py
```

- `-bind` makes a host directory visible inside the container. Without it, only the user's home directory is mounted by default.

### 6.3 Docker (not available)

Docker is not available to regular users on this cluster. Granting Docker access to a user is equivalent to granting host root, which is incompatible with a shared multi-user environment.

If you have a Docker image you want to use, two options:

1. Convert it to an Apptainer `.sif` file (see §6.2). This works for most public images.
2. Recreate the relevant setup as a conda environment.

For most ML workflows, conda is the default. Use containers only when the workload depends on system-level components that conda cannot provide.

### 6.4 Useful environment variables inside a job

| Variable | Meaning |
| --- | --- |
| `SLURM_JOB_ID` | Your job ID |
| `SLURM_JOB_NAME` | Your job name |
| `SLURM_JOB_NODELIST` | Nodes assigned |
| `SLURM_CPUS_PER_TASK` | CPUs per task you asked for |
| `SLURM_NTASKS` | Total tasks |
| `SLURM_GPUS_ON_NODE` | GPUs allocated on this node |
| `SLURM_ARRAY_TASK_ID` | Task index in a job array |
| `CUDA_VISIBLE_DEVICES` | GPU indices assigned |
| `SLURM_SUBMIT_DIR` | Directory you ran `sbatch` from |

Use these to make scripts generic:

```bash
torchrun --nproc_per_node=$SLURM_GPUS_ON_NODE train.py
```

---

## 7. Example scripts

### 7.1 Single-GPU training

```bash
#!/bin/bash
#SBATCH --job-name=train_single
#SBATCH --output=logs/%x-%j.out
#SBATCH --time=12:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --gres=gpu:1

source /home/compu/anaconda3/etc/profile.d/conda.sh
conda activate ml

cd $SLURM_SUBMIT_DIR

python train.py \
    --batch-size 64 \
    --lr 0.001 \
    --epochs 100 \
    --output-dir runs/$SLURM_JOB_ID
```

### 7.2 Multi-GPU training with PyTorch DDP

```bash
#!/bin/bash
#SBATCH --job-name=train_ddp
#SBATCH --output=logs/%x-%j.out
#SBATCH --time=24:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=128G
#SBATCH --gres=gpu:4

source /home/compu/anaconda3/etc/profile.d/conda.sh
conda activate ml

cd $SLURM_SUBMIT_DIR

torchrun \
    --standalone \
    --nproc_per_node=4 \
    train.py \
    --batch-size 64 \
    --output-dir runs/$SLURM_JOB_ID
```

Note `--ntasks=1` combined with `--nproc_per_node=4`. `torchrun` spawns its own processes inside the single Slurm task. Asking Slurm for `--ntasks=4` would create four separate Slurm tasks, each spawning four processes, for 16 processes total.

### 7.3 Hyperparameter sweep with a job array

A job array submits many similar jobs in one command. Each gets a unique `SLURM_ARRAY_TASK_ID`.

```bash
#!/bin/bash
#SBATCH --job-name=sweep
#SBATCH --output=logs/%x-%A_%a.out
#SBATCH --time=4:00:00
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
#SBATCH --array=0-11           # 12 tasks indexed 0..11
# Alternative: cap concurrent runs to 4
# #SBATCH --array=0-11%4

LRS=(0.0001 0.0003 0.001)
BSS=(32 64 128 256)

LR_IDX=$(( SLURM_ARRAY_TASK_ID / 4 ))
BS_IDX=$(( SLURM_ARRAY_TASK_ID % 4 ))

LR=${LRS[$LR_IDX]}
BS=${BSS[$BS_IDX]}

source /home/compu/anaconda3/etc/profile.d/conda.sh
conda activate ml

python train.py --lr $LR --batch-size $BS \
    --output-dir runs/sweep/lr${LR}_bs${BS}
```

In the output pattern, `%A` is the array job ID and `%a` is the task ID. Files become `logs/sweep-1234_0.out`, `logs/sweep-1234_1.out`, etc.

Cancel an entire array:

```bash
scancel 1234
```

Cancel one task in an array:

```bash
scancel 1234_5
```

### 7.4 Long job with checkpointing and auto-resume

For runs that exceed any reasonable `--time` limit, set up checkpointing and chain restarts.

```bash
#!/bin/bash
#SBATCH --job-name=long_train
#SBATCH --output=logs/%x-%j.out
#SBATCH --time=24:00:00
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH --signal=B:USR1@300    # send SIGUSR1 300s before time limit

CKPT_DIR=checkpoints/$SLURM_JOB_NAME
mkdir -p $CKPT_DIR

source /home/compu/anaconda3/etc/profile.d/conda.sh
conda activate ml

# Resume from last checkpoint if one exists
RESUME_ARG=""
if [ -f "$CKPT_DIR/latest.pt" ]; then
    RESUME_ARG="--resume $CKPT_DIR/latest.pt"
fi

python train.py --ckpt-dir $CKPT_DIR $RESUME_ARG

# After this job ends (completion or signal), submit a successor unless
# training has reached its target.
if [ ! -f "$CKPT_DIR/finished.flag" ]; then
    sbatch $0
fi
```

- `-signal=B:USR1@300` tells Slurm to send `SIGUSR1` to the batch script 300 seconds before the time limit, giving your code time to save a final checkpoint. The training script must install a signal handler.

### 7.5 Interactive debugging session

```bash
srun --gres=gpu:1 --mem=32G --cpus-per-task=8 --time=2:00:00 --pty bash
```

This drops you into a shell on the compute node with the requested resources allocated. `CUDA_VISIBLE_DEVICES` is set, `nvidia-smi` shows only your GPU, and `python` with CUDA works normally. Type `exit` to release the allocation.

For longer interactive work where you want to run many short commands without re-queuing each time, use `salloc` and launch each command with `srun` (see §2).

### 7.6 Jupyter notebook on a compute node

In one terminal:

```bash
srun --gres=gpu:1 --mem=32G --time=4:00:00 --pty bash
# now on the compute node, inside the allocation
jupyter lab --no-browser --port 8888 --ip 0.0.0.0
```

In a second terminal on your laptop:

```bash
ssh -N -L 8888:gpu01:8888 you@cluster
```

Then open http://localhost:8888 in a browser. Check the URL `jupyter lab` prints for the auth token.

### 7.7 Job that depends on another finishing

```bash
JOBID=$(sbatch --parsable preprocess.sh)
sbatch --dependency=afterok:$JOBID train.sh
```

Or chain in one line:

```bash
sbatch --dependency=afterok:$(sbatch --parsable train.sh) evaluate.sh
```

Common dependency types:

- `afterok`: run only if the previous job succeeded
- `afterany`: run regardless of outcome
- `afternotok`: run only if the previous job failed (useful for cleanup)

---

## 8. Good practices

### Resource requests

- Ask for what you need, not what you wish you had. Larger requests wait longer in the queue.
- Always set `-time`. Without it, the backfill scheduler cannot fit your job into gaps, and wait times increase for everyone.
- Check `MaxRSS` in `sacct` after the job and right-size `-mem` for next time.
- Match CPU and GPU counts to your workload. A common starting point is 8 CPUs per GPU; adjust based on data-loading needs.

### Scheduling and fair-share

The cluster uses fair-share scheduling: users who have consumed many GPU-hours recently get lower priority for new jobs. Two implications:

- If your job sits in the queue at `PD` with reason `Priority`, someone with a higher fair-share score is ahead. Wait, or run something smaller meanwhile.
- Fair-share counts the resources you **actually used**, not what you requested. A job that requested 24 hours but finished in 30 minutes only counts as 30 minutes.

You can see your current fair-share standing with:

```bash
sshare -u $USER
```

Lower `LevelFS` means you have used more than your share recently and will wait longer for the next job. The score rebalances over about a week (see `PriorityDecayHalfLife` in the admin guide).

### Code organization

- Keep code and configs in `$HOME`.
- Write outputs to a dedicated runs directory. `runs/$SLURM_JOB_ID/` keeps experiments tidy and avoids collisions.
- Use `$SLURM_SUBMIT_DIR` inside scripts to reference the directory you submitted from.

### Data handling

> Once `/scratch` is set up, the recommended pattern will be:
> 

```bash
# At job start, copy dataset from NAS to local scratch
mkdir -p /scratch/$SLURM_JOB_ID
rsync -a /nas/datasets/imagenet/ /scratch/$SLURM_JOB_ID/data/

# Train using local scratch (much faster I/O)
python train.py --data /scratch/$SLURM_JOB_ID/data

# At job end, copy results back to persistent storage
rsync -a runs/ /nas/runs/$SLURM_JOB_ID/

# Clean up scratch
rm -rf /scratch/$SLURM_JOB_ID
```

Until `/scratch` is in place, training from NAS works but is slower. For small-file datasets, data loading is often the bottleneck.

### Submission hygiene

- Submit from a clean directory. Each job inherits the submission directory; if it is cluttered, log paths get confusing.
- Check `squeue` after submitting to confirm the job entered the queue as expected.
- Use descriptive job names. `train` and `test` get lost among other users' jobs. `resnet_lr1e3_bs64` is searchable.

---

## 9. SSH and GPU policy

The cluster operates on trust. You can SSH in directly for non-GPU work: editing code, managing conda environments, running CPU-only scripts, browsing files, `git`, and so on.

**All GPU use must go through Slurm.** This means `srun`, `sbatch`, or `salloc` with `--gres=gpu:N`. Do not run CUDA workloads outside a Slurm allocation.

A small safeguard is in place so that accidental GPU use outside Slurm does not happen in ordinary workflows. It is a convenience for honest mistakes, not a security boundary, and it should not be worked around.

---

## 10. Troubleshooting

### Job stuck pending

```bash
squeue -j <jobid>
scontrol show job <jobid> | grep -i reason
```

Common cases:

- **`Resources`**: requested resources are not yet free. Wait, or reduce the request. Use `squeue --start` for the scheduler's estimate.
- **`Priority`**: other jobs are ahead. No action needed.
- **`PartitionTimeLimit`**: `-time` exceeds the partition maximum.
- **`ReqNodeNotAvail`**: a pinned node is down or draining. Remove `-nodelist` if you set it.

### `srun` appears to hang

Usually it is queued, not stuck. After printing something like `srun: job N queued and waiting for resources`, `srun` stays silent until the job can actually start. Open another shell and check:

```bash
squeue -u $USER
```

If the state is `PD` with reason `Resources`, other jobs are using what you asked for. Wait, request less, or use `squeue --start` for an ETA. Press `Ctrl+C` in the original shell to cancel the queued job.

Always set `--time=SHORT` for quick interactive tests so the job will not wait forever, and so it does not block other users if you forget to cancel it.

### Job failed immediately

```bash
cat logs/<job-output>.out
cat logs/<job-output>.err
scontrol show job <jobid>   # look at ExitCode
```

Common causes:

- **`logs/` does not exist.** Slurm cannot open the output file and the job exits at line 1. Create the directory before submitting.
- **`conda: command not found`.** Add `source /home/compu/anaconda3/etc/profile.d/conda.sh` before `conda activate`. Slurm scripts do not source `.bashrc`.
- **`No such file or directory`.** The working directory differs from what you expected. Use absolute paths or `cd $SLURM_SUBMIT_DIR` at the top of the script.

### `torch.cuda.is_available()` returns False outside Slurm

Expected. GPU access is only available inside a Slurm allocation. Submit your code with `srun`, `sbatch`, or `salloc` and `--gres=gpu:N` (see §9).

### Job killed for memory (OOM)

Exit code includes `0:9` and state in `sacct` is `OOM_KILL` or similar. The `slurmd.log` will show `Detected oom_kill event`. Options, in order:

1. Increase `-mem`.
2. Reduce batch size.
3. Enable gradient checkpointing or mixed precision.
4. Check for memory leaks, especially in data loaders.

Use `sacct --format=JobID,MaxRSS,ReqMem` to see how much memory the job actually used; this is the right starting point for the new `--mem` value.

### Job hit the time limit

State is `TIMEOUT`. Options:

1. Increase `-time` (up to the 24-hour cluster maximum).
2. Add checkpointing and chain restarts (§7.4).
3. Profile and optimize.

### `Requested time limit exceeds partition's maximum`

The cluster has a 24-hour hard ceiling per job. Requests with `--time` greater than `24:00:00` (or `1-00:00:00`) are rejected at submission. Long runs need to be broken up with checkpointing (§7.4).

### Not all requested GPUs visible inside the job

Inside the job:

```bash
echo "GPUs assigned: $SLURM_GPUS_ON_NODE"
echo "CUDA_VISIBLE_DEVICES: $CUDA_VISIBLE_DEVICES"
nvidia-smi -L
```

If the counts disagree with what you requested, report to the admin with the job ID.

### `Unable to allocate resources`

The requested resources do not exist. Possible causes:

- `-mem=999G` on a 256 GB node
- `-gres=gpu:8` on a 4-GPU node
- `-partition=nonexistent`

Check available resources:

```bash
sinfo -o "%n %c %m %G"
```

### Job runs but writes no output

stdout is buffered. Force flushing:

```bash
python -u train.py
# or
PYTHONUNBUFFERED=1 python train.py
```

### Output file mixes stdout and stderr unexpectedly

If you set only `--output`, both streams go there. To split:

```bash
#SBATCH --output=logs/%x-%j.out
#SBATCH --error=logs/%x-%j.err
```

### Attaching a shell to a running job

If you want to inspect a running job on the compute node:

```bash
srun --jobid=<your-job-id> --pty bash
```

This attaches a shell to the existing job's allocation. From there you can run `nvidia-smi`, `htop`, or anything else within the job's resource limits.

---

## 11. Cheat sheet

```
# Submit
sbatch script.sh
srun --time=10:00 --mem=4G python test.py
salloc --gres=gpu:1 --time=2:00:00

# Monitor
squeue                  squeue -u $USER       squeue --start
scontrol show job 123   sacct -j 123          tail -f logs/...

# Control
scancel 123             scancel -u $USER      scancel --state=PD -u $USER
scontrol update JobId=123 TimeLimit=48:00:00
scontrol hold 123       scontrol release 123

# Inspect cluster
sinfo                   sinfo -N -l           sinfo -o "%n %c %m %G"

# Common flags
--time=HH:MM:SS         --mem=64G             --cpus-per-task=8
--gres=gpu:N            --nodes=1             --ntasks=1
--array=0-9             --dependency=afterok:123
--output=logs/%x-%j.out --signal=B:USR1@300
```

---

## 12. Further reading

- Official docs: https://slurm.schedmd.com/
- `man sbatch` on the cluster: every flag, accurate to the installed version.
- **Slurm Setup Guide (for admin)** for understanding why the cluster is configured the way it is.