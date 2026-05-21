FROM andrius/asterisk:latest

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        ffmpeg \
        python3 \
    && rm -rf /var/lib/apt/lists/*

COPY pbx/asterisk/extensions.conf /opt/kpi-asterisk/etc/extensions.conf
COPY pbx/asterisk/http.conf /opt/kpi-asterisk/etc/http.conf
COPY pbx/asterisk/pjsip.conf /opt/kpi-asterisk/etc/pjsip.conf
COPY pbx/asterisk/rtp.conf /opt/kpi-asterisk/etc/rtp.conf
COPY pbx/assets/idle_timeout.wav /opt/kpi-asterisk/sounds/idle_timeout.wav
COPY pbx/assets/next_question.wav /opt/kpi-asterisk/sounds/next_question.wav
COPY pbx/assets/welcome.wav /opt/kpi-asterisk/sounds/welcome.wav
COPY pbx/scripts/kpi_audio_has_speech.py /usr/local/bin/kpi_audio_has_speech.py
COPY pbx/scripts/kpi_phone_assistant.py /usr/local/bin/kpi_phone_assistant.py
COPY pbx/scripts/kpi_record_question.py /usr/local/bin/kpi_record_question.py
COPY pbx/scripts/asterisk_entrypoint.sh /usr/local/bin/kpi_asterisk_entrypoint.sh

RUN mkdir -p /opt/kpi-asterisk/sounds \
    && ffmpeg -hide_banner -loglevel error -y \
        -f lavfi -i sine=frequency=880:duration=0.25 \
        -ar 8000 -ac 1 -sample_fmt s16 /opt/kpi-asterisk/sounds/beep.wav \
    && ffmpeg -hide_banner -loglevel error -y \
        -f lavfi -i sine=frequency=220:duration=0.35 \
        -ar 8000 -ac 1 -sample_fmt s16 /opt/kpi-asterisk/sounds/beeperr.wav \
    && chmod +x /usr/local/bin/kpi_audio_has_speech.py \
    && chmod +x /usr/local/bin/kpi_phone_assistant.py \
    && chmod +x /usr/local/bin/kpi_record_question.py \
    && chmod +x /usr/local/bin/kpi_asterisk_entrypoint.sh \
    && mkdir -p \
        /var/lib/asterisk/sounds/kpi/responses \
        /var/log/asterisk \
        /var/log/asterisk/cdr-csv \
        /var/run/asterisk \
        /var/spool/asterisk/recording/kpi \
    && chown -R asterisk:asterisk \
        /etc/asterisk \
        /var/lib/asterisk \
        /var/log/asterisk \
        /var/run/asterisk \
        /var/spool/asterisk

EXPOSE 5060/udp 8088/tcp 10000-10020/udp

CMD ["/usr/local/bin/kpi_asterisk_entrypoint.sh"]
