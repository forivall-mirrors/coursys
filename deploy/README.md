## Proddev VM Setup

Start with a `vagrant up`. Create `courses/localsettings.py` with `localsettings-proddev-example.py` as a template.
In the VM (`vagrant ssh`),
```sh
cd /coursys
docker-compose -f docker-compose.yml -f docker-compose-proddev.yml up -d
./manage.py migrate
./manage.py loaddata fixtures/*.json
./manage.py update_index
make proddev-start-all
```

## Demo Server Setup

See `instructions/DEMO_SERVER_SETUP.md`.

## Proddev VM Setup: different user

This is used to test having a different login/sudo user from the user running the CourSys code, as we do in production. In the `Vagrantfile`, set the username in `CONFIG` to "coursys" and comment-out the `config.vm.synced_folder` line. 

Start with a `vagrant up`. In the VM (`vagrant ssh`),
```sh
sudo su -l coursys
cd /coursys
```

Create `courses/localsettings.py` with `localsettings-proddev-example.py` as a template.
```sh
docker-compose -f docker-compose.yml -f docker-compose-proddev.yml up -d
./manage.py migrate
./manage.py loaddata fixtures/*.json
./manage.py update_index
make proddev-start
make start-all
```


## Production Server Setup

Get a VM. Do a `ssh-copy-id`.

```sh
sudo apt install git chef
git clone -b deployed-2020 https://github.com/sfu-fas/coursys.git
cd coursys
cp ./deploy/run-list-production.json ./deploy/run-list.json
# check ./deploy/solo.rb and ./deploy/run-list-production.json
make chef # will fail at nginx step because of missing cert...
cd /coursys
sudo cp ./deploy/run-list-production.json ./deploy/run-list.json
# re-check ./deploy/solo.rb and ./deploy/run-list.json from this installation
sudo rm -rf ~/coursys # probably: it's all in /coursys now
```

Double-check firewall rules: these recipes do not configure iptables, but only ports 80 and 443 should be open. Port 22 should be open to a limited IP range.

To bootstrap the SSL certificates, either copy /etc/letsencrypt on a previous production server,
or comment-out all SSL server blocks from the Nginx configs so certbot can bring up Nginx to bootstrap and:
```sh
sudo certbot --nginx
make chef
```

Check local settings:
```sh
sudo nano -w /coursys/courses/localsettings.py
sudo nano -w /coursys/courses/secrets.py
```
