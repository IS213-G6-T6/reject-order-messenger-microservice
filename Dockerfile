FROM python:3-slim
WORKDIR /usr/src/app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY ./amqp_setup.py .
COPY ./reject_order.py .
COPY ./invokes.py .
CMD [ "python", "./reject_order.py" ]
