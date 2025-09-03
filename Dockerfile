# Usa uma imagem base do Python 3.11
FROM python:3.11-slim

# Instala as dependências de sistema do Geopandas (GDAL etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal-dev \
    g++ \
 && rm -rf /var/lib/apt/lists/*

# Cria um diretório para a aplicação
WORKDIR /app

# Copia os arquivos da aplicação para o container
COPY . /app

# Instala as bibliotecas Python
RUN pip install --no-cache-dir \
    Flask \
    gunicorn \
    geopandas \
    wntr

# Expõe a porta que o gunicorn irá rodar
EXPOSE 8000

# Comando para rodar a aplicação em produção
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "app:app"]