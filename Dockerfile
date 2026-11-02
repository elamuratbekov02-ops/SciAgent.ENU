FROM python:3.13-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY static static
COPY data/seed.json data/form_schema.json data/f605_template.xlsx data/f605_layout.json data/
ENV SCIAGENT_DB=/srv/storage/sciagent.db SCIAGENT_UPLOADS=/srv/storage/uploads
RUN useradd -m app && mkdir -p /srv/storage && chown -R app /srv/storage
USER app
EXPOSE 8605
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8605}"]
