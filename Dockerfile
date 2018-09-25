FROM python:2
ADD main.py /
ADD requirements.txt /
ADD exchange /exchange
ENV PYTHONUNBUFFERED=0
RUN pip install -r requirements.txt
CMD ["python2", "-u", "./main.py"]
