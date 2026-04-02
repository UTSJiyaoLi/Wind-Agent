import os
import shlex


def main() -> None:
    model_path = os.getenv("MODEL_PATH", "/share/home/lijiyao/CCCC/Models/llms/gpt-oss-20b")
    host = os.getenv("VLLM_HOST", "0.0.0.0")
    port = os.getenv("VLLM_PORT", "8004")
    max_model_len = os.getenv("VLLM_MAX_MODEL_LEN", "8192")
    dtype = os.getenv("VLLM_DTYPE", "bfloat16")

    # "2nd card" convention: GPU index 1.
    os.environ["CUDA_VISIBLE_DEVICES"] = os.getenv("CUDA_VISIBLE_DEVICES", "1")

    cmd = [
        "vllm",
        "serve",
        model_path,
        "--host",
        host,
        "--port",
        str(port),
        "--dtype",
        dtype,
        "--max-model-len",
        str(max_model_len),
    ]

    print("[start_vllm_gpt_oss20b_gpu1] CUDA_VISIBLE_DEVICES=", os.environ["CUDA_VISIBLE_DEVICES"])
    print("[start_vllm_gpt_oss20b_gpu1] cmd:", " ".join(shlex.quote(x) for x in cmd))
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main()
