.DEFAULT_GOAL := help

DOCKER ?= docker
COMPOSE := $(DOCKER) compose --file compose.yaml
IMAGE_PREFIX ?= voice-smiths
TAG ?= latest
PLATFORM ?=
DIST_DIR ?= dist/images
ARCHIVE ?= $(DIST_DIR)/voice-smiths-$(TAG).tar

export IMAGE_PREFIX TAG
ifneq ($(strip $(PLATFORM)),)
export DOCKER_DEFAULT_PLATFORM := $(PLATFORM)
endif

.PHONY: help config build build-backend build-frontend up start down stop restart logs ps save package load push

help:
	@printf '%s\n' \
	  'make build           构建前后端镜像' \
	  'make build-backend   仅构建后端镜像' \
	  'make build-frontend  仅构建前端镜像' \
	  'make up              构建并启动，等待服务健康' \
	  'make start           使用已有镜像启动（离线导入后使用）' \
	  'make down            停止并移除容器，保留文件和数据库' \
	  'make stop            停止容器' \
	  'make restart         重启服务' \
	  'make logs            跟踪服务日志' \
	  'make ps              查看服务状态' \
	  'make config          检查 Compose 配置' \
	  'make save            构建并导出两个镜像为 tar 文件' \
	  'make load            从 ARCHIVE 指定的 tar 文件导入镜像' \
	  'make push            推送镜像到 IMAGE_PREFIX 指定的仓库' \
	  '变量：IMAGE_PREFIX=voice-smiths TAG=latest PLATFORM=linux/amd64 WEB_PORT=8080'

config:
	$(COMPOSE) config --quiet

build:
	$(COMPOSE) build

build-backend:
	$(COMPOSE) build backend

build-frontend:
	$(COMPOSE) build frontend

up:
	$(COMPOSE) up --detach --build --wait --wait-timeout 120

start:
	$(COMPOSE) up --detach --no-build --pull never --wait --wait-timeout 120

down:
	$(COMPOSE) down

stop:
	$(COMPOSE) stop

restart:
	$(COMPOSE) restart

logs:
	$(COMPOSE) logs --follow --tail 100

ps:
	$(COMPOSE) ps

save: build
	mkdir -p "$(dir $(ARCHIVE))"
	$(DOCKER) image save --output "$(ARCHIVE)" "$(IMAGE_PREFIX)-backend:$(TAG)" "$(IMAGE_PREFIX)-frontend:$(TAG)"

package: save

load:
	$(DOCKER) image load --input "$(ARCHIVE)"

push:
	$(COMPOSE) push

build-backend:
	$(DOCKER) buildx build --platform linux/amd64 -t backend:v0.0.1 .

build-frontend:
	$(DOCKER) buildx --platform linux/amd64 -t frontend:v0.0.1 -f ./frontend/Dockerfile
