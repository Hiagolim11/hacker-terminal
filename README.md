# Hacker Terminal

Um terminal retrô, leve e nativo para Linux, construído com Python, GTK 3 e VTE. É um terminal real — ANSI, Unicode, `tmux`, `vim`, prompts Powerline e programas de tela cheia funcionam pelo mesmo motor usado por terminais GTK maduros.

> As ações incluídas são locais e defensivas. Use ferramentas de segurança apenas em sistemas próprios ou com autorização explícita.

## Destaques

- shell de login real (`$SHELL`, `zsh` ou `bash`) dentro de um PTY;
- seleção automática de Nerd Font com verificação real dos glifos Powerline;
- fallback seguro para Hack, Fira Code, DejaVu Sans Mono e Monospace;
- padrão profissional Minimal Dark; boot, chuva digital, scanlines e sons permanecem opcionais;
- painel de diagnóstico local responsivo, com rolagem própria, rede, portas, processos e saúde do sistema, ocultado automaticamente em janelas estreitas;
- barra de status com tema, diretório atual, branch Git e ambiente virtual;
- histórico com rolagem vertical nativa e 20 mil linhas;
- sessões em abas, pesquisa no histórico e títulos dinâmicos;
- divisões horizontais e verticais com restauração do layout;
- cinco temas integrados e suporte a temas personalizados importáveis;
- perfis Desenvolvimento, Foco e Retro Hacker, além de perfis personalizados com ações próprias;
- ações rápidas personalizáveis e paleta de comandos pesquisável;
- herança de diretório e restauração segura da sessão anterior;
- links com `Ctrl+clique` e contexto de branch Git/ambiente virtual;
- atalhos de teclado totalmente configuráveis, com detecção de conflitos;
- editor visual de temas com cores da interface, do terminal e paleta ANSI;
- cursor, opacidade, shell, cópia ao selecionar e rolagem configuráveis;
- som de teclado mecânico (Red, Brown, Blue ou pacotes gravados) com baixa latência;
- confirmação de colagem perigosa, aviso de bell e gravação automática da sessão;
- log rotativo de diagnóstico e modo `--debug`;
- preferências persistentes em `~/.config/hacker-terminal/config.ini`;
- copiar/colar, menu contextual, zoom e modo de tela cheia;
- tema próprio, sem Electron, navegador, telemetria ou acesso externo;
- instalador por usuário e desinstalação limpa.

## Dependências

No Debian, Ubuntu ou Kali Linux:

```bash
sudo apt update
sudo apt install python3 python3-gi gir1.2-gtk-3.0 gir1.2-vte-2.91 python3-gst-1.0
```

O GStreamer é opcional; sem ele, apenas os sons são desativados. Uma Nerd Font não é obrigatória, mas é recomendada para prompts com ícones. O app reconhece automaticamente famílias como `JetBrainsMono Nerd Font Mono`, `FiraCode Nerd Font Mono`, `MesloLGS NF` e outras variantes instaladas.

## Executar

```bash
./run.sh
```

Antes de abrir a interface, confira a instalação e a fonte escolhida:

```bash
./run.sh --diagnose
```

Para forçar uma fonte ou reduzir animações:

```bash
./run.sh --font "JetBrainsMono Nerd Font Mono" --font-size 12
./run.sh --no-boot --no-effects --no-sound
./run.sh --working-directory ~/projetos
./run.sh -e htop
./run.sh --list-themes
./run.sh --theme cyberpunk-purple
./run.sh --list-profiles
./run.sh --profile focus
```

As mesmas preferências podem ser definidas com `HACKER_TERMINAL_FONT`, `HACKER_TERMINAL_BOOT`, `HACKER_TERMINAL_EFFECTS` e `HACKER_TERMINAL_SOUND`. Use `0`, `false`, `no` ou `off` para desligar uma opção booleana.

## Instalar

```bash
./install.sh
```

Isso instala tudo somente para o usuário atual em `~/.local`, cria o comando `hacker-terminal` e adiciona o app ao menu. Para verificar ou remover:

```bash
./install.sh --check
./install.sh --uninstall
```

### Pacote Debian

Para instalar o pacote pronto no Kali, Debian ou Ubuntu:

```bash
sudo apt install ./hacker-terminal_0.12.0_all.deb
```

O uso de `apt` é recomendado porque ele resolve automaticamente as dependências. Para gerar novamente o pacote a partir do código-fonte:

```bash
make deb
```

## Temas

Abra **Preferências → Tema** para escolher entre Matrix Green, Cyberpunk Purple,
Amber CRT, Ice Blue e Minimal Dark. A mudança é aplicada imediatamente e fica
salva para as próximas janelas. Os botões **Importar** e **Exportar** permitem
compartilhar arquivos `.ini`.

Temas personalizados ficam em:

```text
~/.config/hacker-terminal/themes/
```

Para criar um, exporte um tema existente, altere seu `id`, `name`, autor e cores,
e importe o novo arquivo. O identificador aceita letras minúsculas, números e
hífens; todas as cores usam `#RRGGBB`; `terminal.ansi` exige exatamente 16 cores;
e `scanline_opacity` deve estar entre `0` e `1`. Arquivos inválidos são ignorados
sem impedir a abertura do terminal, que volta com segurança ao Minimal Dark.

## Personalização

**Preferências** (`Ctrl+,`) tem quatro abas:

- **Geral:** perfil, shell personalizado (ex.: `fish` ou `bash --norc`), restauração de sessão, painel lateral, confirmação de colagem e aviso de bell.
- **Aparência:** tema, editor de temas, fonte, opacidade do fundo e efeitos.
- **Terminal:** formato e piscar do cursor, negrito com cores claras, copiar ao selecionar, histórico e comportamento de rolagem.
- **Atalhos:** clique em um atalho e pressione a nova combinação. `Backspace` desativa e `Esc` cancela.

Os atalhos também podem ser editados no `config.ini`, usando a sintaxe do GTK. Use `;` para mais de uma combinação e deixe vazio para desativar:

```ini
[shortcuts]
new_tab = <Primary>t
copy = <Primary><Shift>c;<Primary>Insert
fullscreen =
```

Use `./run.sh --list-shortcuts` para ver os identificadores e as teclas em uso.

### Som de teclado mecânico

Em **Preferências → Som do teclado**, ative o som e escolha o switch:

- **Linear (estilo Red):** só o fundo do curso e o retorno, sem clique.
- **Tátil (estilo Brown):** um leve tique do bump tátil antes do fundo do curso.
- **Clicky (estilo Blue):** o clique brilhante da jaqueta na descida e na subida.

Use o campo **Digite aqui para ouvir…** para testar antes de salvar. Os sons sintetizados são aproximações modeladas a partir da física dos switches. Para o som exato de um teclado real, use **Importar pacote…** com:

- um pacote do [Mechvibes](https://mechvibes.com/) (pasta com `config.json`), ou
- uma pasta com gravações nomeadas `press.wav`, `press2.wav`, `release.wav`, `space-press.wav`, `enter-press.wav`, `large-press.wav` etc. (WAV, OGG, MP3, FLAC ou Opus).

Os pacotes ficam em `~/.local/share/hacker-terminal/soundpacks/`.

### Perfis personalizados

Em **Preferências → Geral**, ajuste tema, fonte, shell, cursor e os demais itens nas outras abas e clique em **Salvar como perfil…**. Escolha nome, descrição e diretório inicial. Ative **Ações rápidas próprias** para que o perfil tenha uma lista separada de ações, iniciada como cópia da atual.

Também é possível salvar pela paleta (`Ctrl+Shift+P` → "Salvar configurações atuais como perfil"). Para trocar de perfil, use as Preferências, a paleta ou a linha de comando:

```bash
./run.sh --list-profiles
./run.sh --profile pentest
```

Os perfis ficam em `~/.config/hacker-terminal/profiles/<id>.ini`, e as ações próprias em `<id>.actions`. O diretório inicial é usado ao abrir o terminal com o perfil.

### Editor de temas

Em **Preferências → Aparência**, **Novo…** e **Duplicar…** criam um tema personalizado a partir do tema selecionado. **Editar…** altera um tema personalizado e **Remover** o apaga. Os temas internos nunca são modificados.

## Diagnóstico

Erros e avisos ficam em `~/.local/state/hacker-terminal/hacker-terminal.log`, com rotação automática e permissão `0600`. Para ver mensagens detalhadas no terminal:

```bash
./run.sh --debug
```

## Fluxo de trabalho

Abra **Preferências → Perfil** para alternar entre Desenvolvimento, Foco e Retro
Hacker. Novas abas herdam o diretório atual da sessão ativa. Ao fechar normalmente,
o aplicativo salva somente o tamanho da janela, a aba ativa e diretórios locais;
processos e conteúdo do terminal não são serializados.

Use **Editar ações…** no painel lateral para adicionar comandos de testes, servidor,
Git ou Docker, reordená-los e exigir confirmação antes de ações sensíveis. A paleta
em `Ctrl+Shift+P` pesquisa essas ações junto com temas, perfis e comandos da interface.

## Atalhos

Padrões abaixo; todos podem ser alterados em **Preferências → Atalhos**.

| Atalho | Ação |
| --- | --- |
| `Ctrl+Shift+C` | Copiar seleção |
| `Ctrl+Shift+V` | Colar |
| `Ctrl+Shift+T` | Nova aba |
| `Ctrl+Shift+W` | Fechar aba |
| `Ctrl+Shift+F` | Pesquisar no histórico |
| `Ctrl+Shift+B` | Mostrar ou ocultar ações laterais (em janelas estreitas, exibe temporariamente) |
| `Ctrl+Shift+P` | Abrir a paleta de comandos |
| `Ctrl+Shift+D` | Dividir horizontalmente |
| `Ctrl+Shift+E` | Dividir verticalmente |
| `Ctrl+Shift+O` | Alternar entre painéis divididos |
| `Ctrl+,` | Preferências |
| `Ctrl+PageUp` / `Ctrl+PageDown` | Navegar entre abas |
| `Ctrl++` (ou `Ctrl+=`) / `Ctrl+-` | Aumentar / diminuir fonte |
| `Ctrl+0` | Restaurar tamanho da fonte |
| `Ctrl` + roda | Alterar tamanho da fonte |
| `F11` | Alternar tela cheia |
| Clique direito | Abrir menu contextual |

## Desenvolvimento

```bash
make check
make check-gui
make run
make deb
```

`make check-gui` usa Xvfb quando não há uma sessão gráfica disponível. O projeto evita dependências Python do PyPI: PyGObject e VTE são bibliotecas do sistema. Consulte [CONTRIBUTING.md](CONTRIBUTING.md) antes de enviar mudanças.

## Licença

[MIT](LICENSE)
