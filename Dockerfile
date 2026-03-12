FROM python:3.11-slim

WORKDIR /code

COPY requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

COPY app /code/app
COPY db /code/db
COPY db_migration.py /code/db_migration.py

ENV MODE=production

CMD ["sh", "-c", "if [ \"$MODE\" = 'development' ]; then fastapi dev app/main.py --host 0.0.0.0 --port 8080; else fastapi run app/main.py --host 0.0.0.0 --port 8080; fi"]
