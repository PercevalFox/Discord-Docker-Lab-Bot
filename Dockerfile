# Debian Slim Base
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

# 1. Installations
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash-completion ca-certificates curl wget git nano vim htop tree unzip \
    iputils-ping net-tools python3 python3-pip bsdutils sudo \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# 2. TTYD
ADD https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64 /usr/bin/ttyd
RUN chmod +x /usr/bin/ttyd

# 3. Timer & Entrypoint Scripts
RUN echo '#!/bin/bash\nREMAINING=60\nwhile [ $REMAINING -gt 0 ]; \
do\nsleep 600\nREMAINING=$((REMAINING-10))\nif [ $REMAINING -gt 0 ]; then\necho -e "\n⚠️  LAB ALERT : Only $REMAINING minutes remaining !" \
| wall\nelse\necho -e "\n🚨  SESSION END..." | wall\nfi\ndone' > /usr/local/bin/timer.sh && chmod +x /usr/local/bin/timer.sh

RUN echo '#!/bin/bash\n/usr/local/bin/timer.sh & \nexec bash' > /usr/local/bin/entrypoint.sh && chmod +x /usr/local/bin/entrypoint.sh

# 4. User Config
RUN useradd -m -s /bin/bash student
RUN echo "student ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/student && chmod 0440 /etc/sudoers.d/student
RUN cp /etc/skel/.bashrc /home/student/.bashrc && chown student:student /home/student/.bashrc

# --- 5. THE SPY (NEW) ---
# Prepare log file
RUN touch /var/log/cmd.log && chown student:student /var/log/cmd.log && chmod 660 /var/log/cmd.log

USER student
WORKDIR /home/student

# Configure Bash to write every command to the log file
# (PROMPT_COMMAND is executed right after each command)
RUN echo 'export PROMPT_COMMAND='\''echo "$(date "+%H:%M:%S") $(history 1 | sed "s/^[ ]*[0-9]\+[ ]*//")" >> /var/log/cmd.log'\''' >> ~/.bashrc

ENTRYPOINT ["ttyd", "-W", "-p", "7681", "/usr/local/bin/entrypoint.sh"]
