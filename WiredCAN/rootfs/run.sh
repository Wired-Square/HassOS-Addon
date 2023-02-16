#! /usr/bin/with-contenv bash
whoami
id

echo $0

nc -lk -p 8099 -e  echo -e 'HTTP/1.1 200 OK\r\nServer: DeskPiPro\r\nDate:$(date)\r\nContent-Type: text/html; charset=UTF8\r\nCache-Control: no-store, no cache, must-revalidate\r\n\r\n<!DOCTYPE html><html><body><p>Wired Square. Seriously!</p></body></html>\r\n\n\n' & 

until false; do
  sleep 14400
done
