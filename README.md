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
  username: 86-18866668888 # Username of Petkit APP (小佩宠物), important to use country code
  password: abcdefghijklmn # MD5 or Raw password
  api_base:       # Optional, default is China server: http://api.petkit.cn/6/
  scan_interval:  # Optional, default is 00:02:00
  feeding_amount: # Optional, default is 10(g), also can be input_number entity id.

  # Multiple accounts
  accounts:
    - username: email1@domain.com
      password: password1
      api_base: http://api.petktasia.com/latest/ # Asia server
      feeding_amount: 20
    - username: email2@domain.com
      password: password2
      api_base: http://api.petkt.com/latest/     # America server
      feeding_amount: input_number.your_feeding_amount_entity_id # min:10, step:10
```
