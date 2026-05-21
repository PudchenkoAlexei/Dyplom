#!/bin/sh
set -eu

mkdir -p \
  /etc/asterisk \
  /var/lib/asterisk/sounds/kpi/responses \
  /var/log/asterisk/cdr-csv \
  /var/run/asterisk \
  /var/spool/asterisk/recording/kpi

cp /opt/kpi-asterisk/etc/extensions.conf /etc/asterisk/extensions.conf
cp /opt/kpi-asterisk/etc/http.conf /etc/asterisk/http.conf
cp /opt/kpi-asterisk/etc/pjsip.conf /etc/asterisk/pjsip.conf
cp /opt/kpi-asterisk/etc/rtp.conf /etc/asterisk/rtp.conf

if [ -n "${KPI_PBX_PUBLIC_IP:-}" ]; then
  sed -i "s/__KPI_PBX_PUBLIC_IP__/${KPI_PBX_PUBLIC_IP}/g" /etc/asterisk/pjsip.conf
else
  sed -i "/__KPI_PBX_PUBLIC_IP__/d" /etc/asterisk/pjsip.conf
fi

cp /opt/kpi-asterisk/sounds/beep.wav /var/lib/asterisk/sounds/beep.wav
cp /opt/kpi-asterisk/sounds/beeperr.wav /var/lib/asterisk/sounds/beeperr.wav
rm -f \
  /var/lib/asterisk/sounds/kpi/idle_timeout.sln16 \
  /var/lib/asterisk/sounds/kpi/next_question.sln16 \
  /var/lib/asterisk/sounds/kpi/welcome.sln16
cp /opt/kpi-asterisk/sounds/idle_timeout.wav /var/lib/asterisk/sounds/kpi/idle_timeout.wav
cp /opt/kpi-asterisk/sounds/next_question.wav /var/lib/asterisk/sounds/kpi/next_question.wav
cp /opt/kpi-asterisk/sounds/welcome.wav /var/lib/asterisk/sounds/kpi/welcome.wav

chown -R asterisk:asterisk \
  /etc/asterisk \
  /var/lib/asterisk \
  /var/log/asterisk \
  /var/run/asterisk \
  /var/spool/asterisk

exec asterisk -f -vvv -U asterisk -G asterisk
