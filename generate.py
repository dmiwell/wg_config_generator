#!/usr/bin/env python3

from collections import defaultdict
from hashlib import md5
from shutil import copyfile
from subprocess import run, PIPE
import os
import json
from typing import AnyStr
from pydantic import BaseModel, Field


WORK_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = f'{WORK_DIR}/config'
CONFIG_GENERATED = f'{CONFIG_DIR}/config_latest.json'
CONFIG = f'{CONFIG_DIR}/config.json'
WG_CONF_DIR = f'{WORK_DIR}/generated'


def md5_hash(data: AnyStr) -> str:
    data_bytes = data if isinstance(data, bytes) else data.encode('utf-8') # type: ignore
    return md5(data_bytes).hexdigest()


class KeyPair(BaseModel):
  public: str
  private: str


def make_key_pair() -> KeyPair:
  private = run(['wg', 'genkey',], stdout=PIPE, encoding='utf-8').stdout.strip()
  public = run(['wg', 'pubkey'], input=private, stdout=PIPE, encoding='utf-8').stdout.strip()
  return KeyPair(private=private, public=public)

  

class ServerConfig(BaseModel):
  keys: KeyPair = Field(default_factory=make_key_pair)
  endpoint: str


class ClientConfig(BaseModel):
  names: tuple[str, ...]
  keys: dict[str, KeyPair] = Field(default_factory=lambda: defaultdict(make_key_pair))


class Config(BaseModel):
  server: ServerConfig
  clients: dict[str, ClientConfig] = Field(default_factory=dict)

  
def generate_config() -> Config:
  with open(CONFIG, 'r') as f:
    config = Config(**json.loads(f.read()))
    
    for val in config.clients.values():
      for name in val.names:
        val.keys[name]
  
  if os.path.exists(CONFIG_GENERATED):
    with open(CONFIG_GENERATED, 'r')  as f:
      backup_name = f'{CONFIG_DIR}/config_{md5_hash(f.read())}.json'
      copyfile(CONFIG_GENERATED, backup_name)
      print(f'Existing generated config saved as {backup_name}\n')
  
  with open(CONFIG_GENERATED, 'w') as f:
    json.dump(config.dict(), f, indent=2, sort_keys=True)
    print(f'New generated config saved as {CONFIG_GENERATED}. If you need to keep generated keys run:\ncp {CONFIG_GENERATED} {CONFIG}\n')
  
  return config

def normalize_config(config: str) -> str: 
  return '\n'.join(line.strip(' ') for line in config.split('\n')).strip() + '\n'
   

def save_config(config: str, name: str): 
  filename = f'{WG_CONF_DIR}/{name}.conf'
  with open(filename, 'w') as f:
    f.write(normalize_config(config))
    print(f'Wireguard config -> {filename}')
    

def generate_wg_configs():
  config = generate_config()
  
  with open(f'{WORK_DIR}/generated/wg0.conf', 'w') as f:
    server_conf = f'''
      [Interface]
      Address = 10.8.0.1/24
      PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
      PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE
      ListenPort = 51820
      PrivateKey = {config.server.keys.private}
      
    '''
    
    ip_count = 1
    for group, group_config in config.clients.items():
      for key_name in group_config.names:
        key_val = group_config.keys[key_name]
        client_config_name = f'{group}_{key_name}'
        ip_count += 1
        server_conf += f'''
          [Peer]
          # {client_config_name}
          PublicKey = {key_val.public}
          AllowedIps = 10.8.0.{ip_count}/32
        '''
        
        client_conf = f'''
          [Interface]
          PrivateKey = {key_val.private}
          Address = 10.8.0.{ip_count}/24
          DNS = 1.1.1.1, 1.0.0.1

          [Peer]
          PublicKey = {config.server.keys.public}
          AllowedIPs = 0.0.0.0/0
          Endpoint = {config.server.endpoint}
          PersistentKeepalive = 25
        '''
        save_config(client_conf, client_config_name)
        

    save_config(server_conf, 'wg0')
    

generate_wg_configs()
exit(0)