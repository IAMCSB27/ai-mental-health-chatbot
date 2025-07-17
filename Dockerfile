# Use official Python base image
FROM python:3.9

# Create a user (non-root) for Hugging Face
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

# Set working directory
WORKDIR /app

# Install dependencies
COPY --chown=user requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# Copy all app files
COPY --chown=user . .

# Run Flask app on port 7860 (Hugging Face default)
ENV PORT=7860
CMD ["python", "app.py"]
