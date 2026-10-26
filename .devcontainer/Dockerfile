# Imagem enxuta de Python (já traz make e git) para o Codespace.
FROM mcr.microsoft.com/devcontainers/python:1-3.11-bookworm

# A imagem vem com o repositório apt do Yarn, cuja chave GPG está vencida. Isso faz o
# `apt-get update` falhar ("The repository 'https://dl.yarnpkg.com/debian stable
# InRelease' is not signed") e derruba a instalação do Docker-in-Docker, que roda
# depois desta etapa. O projeto não usa Yarn, então o repositório sai.
RUN rm -f /etc/apt/sources.list.d/yarn.list
