FROM python:3.11-slim

WORKDIR /app

# Copy dependency definition
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Set environment defaults
ENV HOST=0.0.0.0
ENV PORT=8080

# Expose the port
EXPOSE 8080

# Command to run the application
CMD ["python", "app.py"]
