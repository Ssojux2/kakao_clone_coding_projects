#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_NAME="langchain"
ENV_FILE="$PROJECT_DIR/environment.yml"

usage() {
  cat <<'EOF'
Kanana Schedule Agent runner

Usage:
  ./run.sh                 Sync uv env if needed, then run the Gradio app
  ./run.sh --install       Run uv sync, then run the Gradio app
  ./run.sh --golden        Run golden scenario tests with uv
  ./run.sh --test          Run pytest + golden scenario tests with uv
  ./run.sh --make-student-copy [DIR]
                           Build a student distribution with reference answers stripped
  ./run.sh --conda [ARGS]  Use the legacy conda environment.yml runner
  ./run.sh --help          Show this help

First-time setup:
  ./run.sh --install
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

cd "$PROJECT_DIR"

run_uv() {
  if ! command -v uv >/dev/null 2>&1; then
    echo "uv를 찾을 수 없습니다. https://docs.astral.sh/uv/ 에서 uv를 먼저 설치해주세요." >&2
    exit 1
  fi

  export PYTHONNOUSERSITE=1

  case "${1:-}" in
    "")
      uv run python app.py
      ;;
    --install)
      uv sync
      uv run python app.py
      ;;
    --golden)
      uv run python -m run_golden
      ;;
    --test)
      uv run pytest -q
      uv run python -m run_golden
      ;;
    --make-student-copy)
      uv run python -m scripts.make_student_distribution "${2:-}"
      ;;
    *)
      echo "알 수 없는 옵션입니다: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
}

conda_env_exists() {
  conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"
}

run_conda() {
  if ! command -v conda >/dev/null 2>&1; then
    echo "conda를 찾을 수 없습니다. Miniconda 또는 Anaconda를 먼저 설치해주세요." >&2
    exit 1
  fi

  CONDA_BASE="$(conda info --base)"
  # shellcheck source=/dev/null
  source "$CONDA_BASE/etc/profile.d/conda.sh"

  if [[ "${1:-}" == "--install" ]]; then
    if conda_env_exists; then
      echo "Updating conda env: $ENV_NAME"
      conda env update -n "$ENV_NAME" -f "$ENV_FILE" --prune
    else
      echo "Creating conda env: $ENV_NAME"
      conda env create -f "$ENV_FILE"
    fi
  elif ! conda_env_exists; then
    echo "conda env '$ENV_NAME'가 없어 environment.yml로 새로 만듭니다."
    conda env create -f "$ENV_FILE"
  fi

  conda activate "$ENV_NAME"
  export PYTHONNOUSERSITE=1

  case "${1:-}" in
    "")
      python app.py
      ;;
    --install)
      python app.py
      ;;
    --golden)
      python -m run_golden
      ;;
    --test)
      pytest -q
      python -m run_golden
      ;;
    --make-student-copy)
      python -m scripts.make_student_distribution "${2:-}"
      ;;
    *)
      echo "알 수 없는 conda 옵션입니다: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
}

if [[ "${1:-}" == "--conda" ]]; then
  shift
  run_conda "$@"
else
  run_uv "$@"
fi
