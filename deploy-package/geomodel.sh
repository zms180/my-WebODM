#!/bin/bash
set -eo pipefail
__dirname=$(cd "$(dirname "$0")"; pwd -P)
cd "${__dirname}"

# GeoModel 启动脚本

platform="Linux" # Assumed
uname=$(uname)
case $uname in
    "Darwin")
    platform="MacOS / OSX"
    ;;
    MINGW*)
    platform="Windows"
    ;;
esac

if [[ $platform = "Windows" ]]; then
    export COMPOSE_CONVERT_WINDOWS_PATHS=1
fi

gpu=false
detached=false
load_micmac_node=false

# define realpath replacement function
if [[ $platform = "MacOS / OSX" ]]; then
    realpath() {
        [[ $1 = /* ]] && echo "$1" || echo "$PWD/${1#./}"
    }
fi

# 检查 .env 文件
if [ ! -f .env ]; then
    echo "错误：未找到 .env 配置文件"
    echo "请复制 .env.example 为 .env 并修改配置"
    exit 1
fi

# 加载默认值
source .env
DEFAULT_PORT="$WO_PORT"
DEFAULT_HOST="$WO_HOST"
DEFAULT_MEDIA_DIR="$WO_MEDIA_DIR"
DEFAULT_DB_DIR="$WO_DB_DIR"
DEFAULT_NODE_DIR="$WO_NODE_DIR"
DEFAULT_SSL="$WO_SSL"
DEFAULT_SSL_INSECURE_PORT_REDIRECT="$WO_SSL_INSECURE_PORT_REDIRECT"
DEFAULT_BROKER="$WO_BROKER"
DEFAULT_NODES="$WO_DEFAULT_NODES"
DEFAULT_NODE_MEMORY="$WO_NODE_MEMORY"
DEFAULT_NODE_CPUS="$WO_NODE_CPUS"

# Parse args for overrides
POSITIONAL=()
while [[ $# -gt 0 ]]
do
key="$1"

case $key in
    --port)
    export WO_PORT="$2"
    shift # past argument
    shift # past value
    ;;
    --hostname)
    export WO_HOST="$2"
    shift # past argument
    shift # past value
    ;;
    --media-dir)
    WO_MEDIA_DIR=$(realpath "$2")
    export WO_MEDIA_DIR
    shift # past argument
    shift # past value
    ;;
    --db-dir)
    WO_DB_DIR=$(realpath "$2")
    export WO_DB_DIR
    shift # past argument
    shift # past value
    ;;
    --node-dir)
    WO_NODE_DIR=$(realpath "$2")
    export WO_NODE_DIR
    shift # past argument
    shift # past value
    ;;
    --ssl)
    export WO_SSL=YES
    shift # past argument
    ;;
    --ssl-key)
    WO_SSL_KEY=$(realpath "$2")
    export WO_SSL_KEY
    shift # past argument
    shift # past value
    ;;
    --ssl-cert)
    WO_SSL_CERT=$(realpath "$2")
    export WO_SSL_CERT
    shift # past argument
    shift # past value
    ;;
    --ssl-insecure-port-redirect)
    export WO_SSL_INSECURE_PORT_REDIRECT="$2"
    shift # past argument
    shift # past value
    ;;
    --debug)
    export WO_DEBUG=YES
    shift # past argument
    ;;
    --dev-watch-plugins)
    export WO_DEV_WATCH_PLUGINS=YES
    shift # past argument
    ;;
    --dev)
    export WO_DEBUG=YES
    export WO_DEV=YES
    shift # past argument
    ;;
    --gpu)
    gpu=true
    shift # past argument
    ;;
    --broker)
    export WO_BROKER="$2"
    shift # past argument
    shift # past value
    ;;
    --detached)
    detached=true
    shift # past argument
    ;;
    --default-nodes)
    export WO_DEFAULT_NODES="$2"
    shift # past argument
    shift # past value
    ;;
    --node-memory)
    WO_NODE_MEMORY="$2"
    export WO_NODE_MEMORY
    shift # past argument
    shift # past value
    ;;
    --node-cpus)
    WO_NODE_CPUS="$2"
    export WO_NODE_CPUS
    shift # past argument
    shift # past value
    ;;
    --settings)
    WO_SETTINGS=$(realpath "$2")
    export WO_SETTINGS
    shift # past argument
    shift # past value
    ;;
    --worker-memory)
    WO_WORKER_MEMORY="$2"
    export WO_WORKER_MEMORY
    shift # past argument
    shift # past value
    ;;
    --worker-cpus)
    WO_WORKER_CPUS="$2"
    export WO_WORKER_CPUS
    shift # past argument
    shift # past value
    ;;
    *)    # unknown option
    POSITIONAL+=("$1") # save it in an array for later
    shift # past argument
    ;;
esac
done
set -- "${POSITIONAL[@]}" # restore positional parameters

if [[ "${WO_DEFAULT_NODES}" -gt 1 ]]; then
    echo "ATTENTION: --default-nodes values greater than 1 are no longer supported."
    export WO_DEFAULT_NODES="1"
fi

# 生成或读取 SECRET_KEY（用于 Django 加密）
get_secret() {
    if [ ! -e ./.secret_key ] && [ -e /dev/random ]; then
        echo "Generating secret in ./.secret_key"
        export WO_SECRET_KEY=$(head -c50 < /dev/random | base64)
        echo $WO_SECRET_KEY > ./.secret_key
    elif [ -e ./.secret_key ]; then
        export WO_SECRET_KEY=$(cat ./.secret_key)
    else
        export WO_SECRET_KEY=""
    fi
}

# 检测 GPU
detect_gpus() {
    export GPU_NVIDIA=false

    if [ "${platform}" = "Linux" ]; then
        set +e
        if lspci | grep -i 'NVIDIA' &> /dev/null; then
            echo "检测到 NVIDIA GPU"
            export GPU_NVIDIA=true
        fi
        set -e
    fi
}

usage() {
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "This program helps to manage the setup/teardown of the docker containers for running GeoModel."
    echo ""
    echo "Commands:"
    echo "  start     启动 GeoModel（默认）"
    echo "  stop      停止 GeoModel"
    echo "  down      停止 GeoModel（同 stop）"
    echo "  restart   重启 GeoModel"
    echo "  status    查看服务状态"
    echo "  logs      查看日志"
    echo ""
    echo "Options:"
    echo "  --port <port>               Set the port that GeoModel should bind to (default: $DEFAULT_PORT)"
    echo "  --hostname <hostname>       Set the hostname that GeoModel will be accessible from (default: $DEFAULT_HOST)"
    echo "  --media-dir <path>          Path where processing results will be stored to (default: $DEFAULT_MEDIA_DIR)"
    echo "  --db-dir <path>             Path where the Postgres db data will be stored to (default: $DEFAULT_DB_DIR)"
    echo "  --node-dir <path>           Path where temporary files will be stored during processing (default: docker container storage)"
    echo "  --default-nodes <num>       Whether to create a processing node attached to GeoModel on startup (default: $DEFAULT_NODES)"
    echo "  --node-memory <amount>      Maximum amount of memory allocated for the default processing node (default: unlimited)"
    echo "  --node-cpus <num>           Maximum number of CPUs allocated for the default processing node (default: all)"
    echo "  --ssl                       Enable SSL"
    echo "  --ssl-key <path>            Manually specify a path to the private key file (.pem)"
    echo "  --ssl-cert <path>           Manually specify a path to the certificate file (.pem)"
    echo "  --ssl-insecure-port-redirect <port>  Insecure port number to redirect from when SSL is enabled (default: $DEFAULT_SSL_INSECURE_PORT_REDIRECT)"
    echo "  --debug                     Enable debug for development environments (default: disabled)"
    echo "  --dev                       Enable development mode (default: disabled)"
    echo "  --broker <url>              Set the URL used to connect to the celery broker (default: $DEFAULT_BROKER)"
    echo "  --detached                  Run GeoModel in detached mode (default: disabled)"
    echo "  --gpu                       Use GPU processing nodes (Linux only) (default: disabled)"
    echo "  --settings <path>           Path to a settings.py file to enable modifications of system settings"
    echo "  --worker-memory <amount>    Maximum amount of memory allocated for the worker process (default: unlimited)"
    echo "  --worker-cpus <num>         Maximum number of CPUs allocated for the worker process (default: all)"
    echo ""
    exit 0
}

# 启动函数
start() {
    get_secret

    if [[ $gpu = true ]]; then
        detect_gpus
    fi

    echo "启动 GeoModel..."
    echo ""
    echo "使用以下配置："
    echo "================================"
    echo "主机地址: $WO_HOST"
    echo "服务端口: $WO_PORT"
    echo "媒体目录: $WO_MEDIA_DIR"
    echo "数据库目录: $WO_DB_DIR"
    echo "节点目录: $WO_NODE_DIR"
    echo "SSL: $WO_SSL"
    echo "Celery Broker: $WO_BROKER"
    echo "默认节点: $WO_DEFAULT_NODES"
    echo "节点内存限制: $WO_NODE_MEMORY"
    echo "节点CPU限制: $WO_NODE_CPUS"
    echo "================================"
    echo ""

    command="docker-compose -f docker-compose.yml"

    if [[ $WO_DEFAULT_NODES -gt 0 ]]; then
        if [[ $gpu = true ]] && [ "${GPU_NVIDIA}" = true ]; then
            command+=" -f docker-compose.nodeodx.yml"
            echo "✓ 启用 GPU 处理节点"
        elif [[ $gpu = false ]]; then
            echo "✓ 未启用 GPU 参数，跳过 GPU 节点"
        else
            echo "✓ 未检测到 GPU，跳过 GPU 节点"
        fi
    fi

    command+=" up"

    if [[ $detached = true ]]; then
        command+=" -d"
    fi

    echo "执行命令: $command"
    echo ""
    eval "$command"

    if [[ $detached = true ]]; then
        echo ""
        echo "等待服务启动..."
        sleep 5

        echo ""
        echo "服务状态："
        docker-compose ps

        echo ""
        echo "================================"
        echo "✓ GeoModel 已启动！"
        echo "================================"
        echo "访问地址: http://$WO_HOST:$WO_PORT"
        echo ""
        echo "常用命令："
        echo "  查看日志: docker-compose logs -f webapp"
        echo "  停止服务: docker-compose down"
        echo "  重启服务: docker-compose restart"
        echo "================================"
    fi
}

# 停止函数
down() {
    echo "停止 GeoModel..."

    command="docker-compose -f docker-compose.yml"

    if [ -f docker-compose.nodeodx.yml ]; then
        command+=" -f docker-compose.nodeodx.yml"
    fi

    command+=" down"

    eval "$command"
    echo "✓ GeoModel 已停止"
}

# 重启函数
restart() {
    down
    echo ""
    start
}

# 查看状态
status() {
    docker-compose ps
}

# 查看日志
logs() {
    docker-compose logs -f
}

# 解析命令
case "${1:-start}" in
    start)
        shift
        start "$@"
        ;;
    stop|down)
        down
        ;;
    restart)
        shift
        restart "$@"
        ;;
    status)
        status
        ;;
    logs)
        logs
        ;;
    -h|--help|help)
        usage
        ;;
    *)
        echo "未知命令: $1"
        echo "使用 '$0 help' 查看帮助"
        exit 1
        ;;
esac
