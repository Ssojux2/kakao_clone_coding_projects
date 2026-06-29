#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_NAME="langchain"
ENV_FILE="$PROJECT_DIR/environment.yml"
PYTHON_VERSION_FILE="$PROJECT_DIR/.python-version"
PROJECT_PYTHON_VERSION="3.11"

if [[ -f "$PYTHON_VERSION_FILE" ]]; then
  PROJECT_PYTHON_VERSION="$(tr -d '[:space:]' < "$PYTHON_VERSION_FILE")"
  PROJECT_PYTHON_VERSION="${PROJECT_PYTHON_VERSION:-3.11}"
fi

usage() {
  cat <<'EOF'
Kanana Schedule Agent runner

Usage:
  ./run.sh                 Run the Week 1 Gradio app
  ./run.sh --weekN         Run the selected week app, where N is 1-6
  ./run.sh --weekN --test  Run pytest + golden scenario tests for the selected week env
  ./run.sh --install       Install uv/Python if needed, sync deps, then run the Week 1 Gradio app
  ./run.sh --golden        Run golden scenario tests with uv
  ./run.sh --test          Run offline pytest + golden scenario tests with uv
  ./run.sh --integration-test
                           Run API-backed integration pytest tests with uv
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

detect_os() {
  local uname_s
  uname_s="$(uname -s 2>/dev/null || true)"

  case "$uname_s" in
    Darwin*) echo "macos" ;;
    Linux*) echo "linux" ;;
    MINGW*|MSYS*|CYGWIN*) echo "windows" ;;
    *) echo "unknown" ;;
  esac
}

prepend_path_dir() {
  local dir="${1:-}"
  [[ -n "$dir" && -d "$dir" ]] || return 0

  case ":${PATH:-}:" in
    *":$dir:"*) ;;
    *) export PATH="$dir:${PATH:-}" ;;
  esac
}

to_unix_path() {
  local path="${1:-}"

  if [[ -n "$path" ]] && command -v cygpath >/dev/null 2>&1; then
    cygpath -u "$path" 2>/dev/null || printf '%s\n' "$path"
  else
    printf '%s\n' "$path"
  fi
}

refresh_tool_paths() {
  prepend_path_dir "$HOME/.local/bin"
  prepend_path_dir "$HOME/.cargo/bin"

  if [[ -n "${USERPROFILE:-}" ]]; then
    prepend_path_dir "$(to_unix_path "$USERPROFILE")/.local/bin"
  fi

  local py user_base
  for py in python3 python py; do
    if command -v "$py" >/dev/null 2>&1; then
      user_base="$("$py" -m site --user-base 2>/dev/null || true)"
      if [[ -n "$user_base" ]]; then
        user_base="$(to_unix_path "$user_base")"
        prepend_path_dir "$user_base/bin"
        prepend_path_dir "$user_base/Scripts"
      fi
      return 0
    fi
  done
}

find_powershell() {
  local candidate
  for candidate in powershell.exe powershell pwsh.exe pwsh; do
    if command -v "$candidate" >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  return 1
}

install_uv_with_shell_installer() {
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://astral.sh/uv/install.sh | sh
  else
    return 1
  fi
}

install_uv_with_powershell() {
  local powershell
  powershell="$(find_powershell)" || return 1
  "$powershell" -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
}

install_uv_with_pip() {
  local py
  for py in python3 python py; do
    if command -v "$py" >/dev/null 2>&1; then
      "$py" -m pip install --user --upgrade uv
      return 0
    fi
  done

  return 1
}

uv_install_failed() {
  cat >&2 <<'EOF'
uv 자동 설치에 실패했습니다.

수동 설치:
  macOS/Linux: curl -LsSf https://astral.sh/uv/install.sh | sh
  Windows PowerShell: powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"

설치 후 터미널을 다시 열거나 PATH를 갱신한 뒤 ./run.sh --install 을 다시 실행해주세요.
EOF
  exit 1
}

ensure_uv_for_install() {
  refresh_tool_paths
  if command -v uv >/dev/null 2>&1; then
    return 0
  fi

  echo "uv를 찾을 수 없어 자동 설치를 진행합니다."
  case "$(detect_os)" in
    windows)
      install_uv_with_powershell || install_uv_with_pip || uv_install_failed
      ;;
    macos|linux|unknown)
      install_uv_with_shell_installer || install_uv_with_pip || uv_install_failed
      ;;
  esac

  refresh_tool_paths
  command -v uv >/dev/null 2>&1 || uv_install_failed
  echo "uv 설치 확인: $(uv --version)"
}

require_uv() {
  refresh_tool_paths
  if command -v uv >/dev/null 2>&1; then
    return 0
  fi

  echo "uv를 찾을 수 없습니다. 첫 설치는 ./run.sh --install 로 진행해주세요." >&2
  echo "문제가 계속되면 https://docs.astral.sh/uv/ 에서 uv 설치를 확인해주세요." >&2
  exit 1
}

sync_uv_environment() {
  echo "Python ${PROJECT_PYTHON_VERSION} 확인/설치 중..."
  uv python install "$PROJECT_PYTHON_VERSION"
  uv sync --python "$PROJECT_PYTHON_VERSION"
}

run_uv() {
  local active_week="${KANANA_ACTIVE_WEEK:-1}"
  if [[ "${1:-}" =~ ^--week([1-6])$ ]]; then
    active_week="${BASH_REMATCH[1]}"
    shift
  fi
  export KANANA_ACTIVE_WEEK="$active_week"
  export PYTHONNOUSERSITE=1

  case "${1:-}" in
    "")
      require_uv
      uv run --python "$PROJECT_PYTHON_VERSION" python app.py
      ;;
    --install)
      ensure_uv_for_install
      sync_uv_environment
      uv run --python "$PROJECT_PYTHON_VERSION" python app.py
      ;;
    --golden)
      require_uv
      uv run --python "$PROJECT_PYTHON_VERSION" python -m run_golden
      ;;
    --test)
      require_uv
      uv run --python "$PROJECT_PYTHON_VERSION" pytest -m "not integration" -q
      uv run --python "$PROJECT_PYTHON_VERSION" python -m run_golden
      ;;
    --integration-test)
      require_uv
      uv run --python "$PROJECT_PYTHON_VERSION" pytest -m integration -q
      ;;
    --help|-h)
      usage
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

  local active_week="${KANANA_ACTIVE_WEEK:-1}"
  if [[ "${1:-}" =~ ^--week([1-6])$ ]]; then
    active_week="${BASH_REMATCH[1]}"
    shift
  fi
  export KANANA_ACTIVE_WEEK="$active_week"

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
      pytest -m "not integration" -q
      python -m run_golden
      ;;
    --integration-test)
      pytest -m integration -q
      ;;
    --help|-h)
      usage
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
