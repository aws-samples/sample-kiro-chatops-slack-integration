FROM public.ecr.aws/lambda/python:3.12

# Install git, unzip, and shared libraries required by kiro-cli-chat
RUN dnf install -y git unzip alsa-lib atk at-spi2-atk cups-libs \
    libdrm libXcomposite libXdamage libXrandr mesa-libgbm \
    pango nss nspr libXtst && dnf clean all

# Install kiro-cli and move to a globally accessible path
RUN curl -fsSL https://cli.kiro.dev/install | bash && \
    cp /root/.local/bin/kiro-cli* /usr/local/bin/ && \
    chmod +x /usr/local/bin/kiro-cli*

# Copy function code
COPY index.py ${LAMBDA_TASK_ROOT}/

# Install boto3
RUN pip install boto3==1.38.35 --target "${LAMBDA_TASK_ROOT}"

CMD ["index.handler"]
