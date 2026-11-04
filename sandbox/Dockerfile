# Analysis sandbox: model-written Python runs here. No secrets, no network (enforced at run time), read-only /data.
FROM python:3.12-slim
RUN pip install --no-cache-dir numpy==2.* pandas==2.* && useradd -u 10001 -M -s /usr/sbin/nologin sandbox
COPY sitecustomize.py /usr/local/lib/python3.12/site-packages/sitecustomize.py
USER 10001
WORKDIR /out
ENTRYPOINT ["python", "-I", "/code/main.py"]
