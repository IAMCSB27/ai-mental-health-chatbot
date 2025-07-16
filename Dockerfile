# Use a lightweight Python image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Copy all files into the container
COPY . .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose the port required by Hugging Face Spaces
EXPOSE 7860

# Start the Flask server
CMD ["python", "app.py"]

