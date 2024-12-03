FROM python:3.11-slim

# Instalar Flask
RUN pip install flask

# Establece el directorio de trabajo
WORKDIR /app

# Copia el contenido al contenedor
COPY . .

# Ejecuta la aplicación
CMD ["python", "app.py"]
