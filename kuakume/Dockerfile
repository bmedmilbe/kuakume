# Use the official Python 3.10 slim image as the base
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 


# Set the working directory inside the container
WORKDIR /app

# Install system dependencies for GeoDjango and PostgreSQL
RUN apt-get update && apt-get install -y --no-install-recommends \
    binutils \
    libproj-dev \
    gdal-bin \
    python3-gdal \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install pipenv
RUN pip install --upgrade pip && pip install pipenv

# Copy Pipfile and Pipfile.lock first to leverage Docker's caching
COPY Pipfile Pipfile.lock /app/

# Install dependencies globally in the container
# --deploy ensures the build fails if Pipfile.lock is out of sync
RUN pipenv install --system --deploy

# Copy the rest of your Django project code into the container
COPY . /app/

# Expose Django's default port
EXPOSE 8000

# Start the Django application
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
