# Petkit for HomeAssistant

## Installing

> [Download](https://github.com/hasscc/petkit/archive/main.zip) and copy `custom_components/xiaomi_miot` folder to `custom_components` folder in your HomeAssistant config folder

```shell
# Auto install via terminal shell
wget -q -O - https://cdn.jsdelivr.net/gh/al-one/hass-xiaomi-miot/install.sh | DOMAIN=petkit REPO_PATH=hasscc/petkit bash -
```


## Config

> Recommend sharing devices to another account

```yaml
# configuration.yaml

petkit:
  # Single account
  username: 86-18866668888 # Username of Petkit APP (小佩宠物)
  password: abcdefghijklmn # MD5 or Raw password
  api_base: # Optional, default is http://api.petkit.cn/6/

  # Multiple accounts
  accounts:
    - username: 86-18866660001
      password: password1
    - username: 86-18866660002
      password: password2
```
