## nonebot七圣卡图生成插件

如需部署，自己搭建后端服务[new-card-img-gen](https://github.com/piovium/new-card-img-gen) 然后改代码，装插件。

别名文件在`map`文件夹下，`NameMap.json` 是 bot 读取的版本。

### 修改别名

prompt示例：对NameMap.json中「名字是“饕噬尽吞”，ID为227041」的卡牌别名信息，增加alias别名：「胖猫天赋」

### 增加含自定义描述的新卡

参考 workFlow  `Generate Something Template` 。 修改相关内容。

在本仓库的[Actions](https://github.com/genius-invokation/nonebot_plugin_7s_card_img/actions)中执行

然后，jule prompt示例：
```
将NameMap.wip.json的新增的卡牌别名增加到NameMap.json里，即进行合并。具体地，

NameMap.json已经有的卡牌，不要进行任何变化，包含顺序；
NameMap.wip.json里新增的卡牌（NameMap.json没有的卡牌），加入到NameMap.json里。
```

jule在完成任务后，请您提交pr，然后联系嘟嘟可进行approve。

## 手动别名维护

### 修改别名

直接在`NameMap.json`里修改对应卡牌的aliases属性。

### 增加含自定义描述版本的新卡

请先生成带有新卡的模板。
```
python3 beta_template.py
```

（需要pip安装package pypinyin）

会生成`NameMap.wip.json`，请和`NameMap.json`比对，将新增的新卡部分修改别名，加入到`NameMap.json`里。


## 别名匹配说明（可以不看）

- 匹配自动忽略标点
- 角色全名有子串匹配，子串不用添加

## 如需帮助

- bot群：565828196 





