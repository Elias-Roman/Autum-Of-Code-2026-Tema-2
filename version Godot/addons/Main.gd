extends Control

# ═══════════════════════════════════════════════════════════
#  Main.gd — escena raíz del juego
#  Controla el tablero visual, HUD y flujo de entrada
# ═══════════════════════════════════════════════════════════

# ── Nodos (se asignan en la escena) ──────────────────────
@onready var grid_container:    GridContainer = $MarginContainer/HBox/LeftPanel/GridContainer
@onready var cmd_input:         LineEdit      = $MarginContainer/HBox/RightPanel/VBox/CmdInput
@onready var log_text:          RichTextLabel = $MarginContainer/HBox/RightPanel/VBox/LogScroll/LogText
@onready var hp_bar:            ProgressBar   = $MarginContainer/HBox/RightPanel/VBox/HUD/HPBar
@onready var hp_label:          Label         = $MarginContainer/HBox/RightPanel/VBox/HUD/HPLabel
@onready var oro_label:         Label         = $MarginContainer/HBox/RightPanel/VBox/HUD/OroLabel
@onready var llave_label:       Label         = $MarginContainer/HBox/RightPanel/VBox/HUD/LlaveLabel
@onready var send_btn:          Button        = $MarginContainer/HBox/RightPanel/VBox/SendBtn
@onready var thinking_label:    Label         = $MarginContainer/HBox/RightPanel/VBox/ThinkingLabel
@onready var combat_panel:      PanelContainer = $CombatOverlay
@onready var combat_orco_hp:    ProgressBar   = $CombatOverlay/VBox/OrcoHPBar
@onready var combat_orco_label: Label         = $CombatOverlay/VBox/OrcoHPLabel
@onready var combat_log:        Label         = $CombatOverlay/VBox/CombatLog
@onready var game_over_panel:   PanelContainer = $GameOverPanel
@onready var game_over_label:   Label         = $GameOverPanel/VBox/ResultLabel
@onready var restart_btn:       Button        = $GameOverPanel/VBox/RestartBtn

# ── Tiles (textures cargadas desde los assets de Kenney) ──
# Se asignan como TextureRect en las celdas del grid
var tile_textures: Dictionary = {}   # símbolo → Texture2D

const TILE_SIZE = 64  # px por celda

# Mapeo símbolo → archivo en Tiles/
const SYMBOL_TO_FILE = {
	"K": "tile_0084.png",   # caballero (knight) — ajustá el número según tu spritesheet
	"O": "tile_0300.png",   # orco
	"C": "tile_0290.png",   # cofre
	"D": "tile_0105.png",   # puerta
	"L": "tile_0295.png",   # llave
	".": "tile_0015.png",   # piso vacío
}

var cell_nodes: Array = []   # Array 2D de TextureRect


func _ready():
	# Conectar señales del GameState
	GameState.board_changed.connect(_on_board_changed)
	GameState.message_posted.connect(_on_message)
	GameState.combat_started.connect(_on_combat_started)
	GameState.combat_ended.connect(_on_combat_ended)
	GameState.game_over.connect(_on_game_over)
	GameState.llm_thinking.connect(_on_thinking)

	# Conectar señales del LLMBridge
	LLMBridge.respuesta_lista.connect(_on_llm_respuesta)
	LLMBridge.error_llm.connect(_on_llm_error)

	# Cargar texturas
	_cargar_texturas()

	# Construir la grilla visual
	_construir_grid()

	# UI inicial
	combat_panel.hide()
	game_over_panel.hide()
	thinking_label.hide()
	cmd_input.grab_focus()

	send_btn.pressed.connect(_on_enviar)
	cmd_input.text_submitted.connect(func(_t): _on_enviar())
	restart_btn.pressed.connect(_reiniciar)

	_on_board_changed()
	_log_bienvenida()


# ═══════════════════════════════════════════════════════════
#  CARGA DE TEXTURAS
# ═══════════════════════════════════════════════════════════

func _cargar_texturas():
	var base = "res://kenney_tiny_dungeon/Tiles/"
	for sym in SYMBOL_TO_FILE:
		var path = base + SYMBOL_TO_FILE[sym]
		if ResourceLoader.exists(path):
			tile_textures[sym] = load(path)
		else:
			# Fallback: rectángulo de color si no existe la textura
			tile_textures[sym] = null


# ═══════════════════════════════════════════════════════════
#  CONSTRUCCIÓN DE LA GRILLA
# ═══════════════════════════════════════════════════════════

func _construir_grid():
	grid_container.columns = GameState.SIZE
	cell_nodes = []

	for r in GameState.SIZE:
		var row = []
		for c in GameState.SIZE:
			var panel = Panel.new()
			panel.custom_minimum_size = Vector2(TILE_SIZE, TILE_SIZE)

			# Fondo del tile (piso)
			var bg = TextureRect.new()
			bg.expand_mode = TextureRect.EXPAND_FILL_PARENT
			bg.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
			bg.texture = tile_textures.get(".", null)
			bg.name = "BG"
			panel.add_child(bg)

			# Sprite de la entidad encima
			var sprite = TextureRect.new()
			sprite.expand_mode = TextureRect.EXPAND_FILL_PARENT
			sprite.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
			sprite.name = "Sprite"
			panel.add_child(sprite)

			grid_container.add_child(panel)
			row.append(panel)
		cell_nodes.append(row)


# ═══════════════════════════════════════════════════════════
#  ACTUALIZAR VISUALIZACIÓN
# ═══════════════════════════════════════════════════════════

func _on_board_changed():
	for r in GameState.SIZE:
		for c in GameState.SIZE:
			var sym = GameState.board[r][c]
			var panel = cell_nodes[r][c]
			var sprite: TextureRect = panel.get_node("Sprite")

			if sym == ".":
				sprite.texture = null
			else:
				sprite.texture = tile_textures.get(sym, null)

			# Colorear celdas sin textura
			if sprite.texture == null and sym != ".":
				sprite.self_modulate = _color_fallback(sym)
			else:
				sprite.self_modulate = Color.WHITE

	_actualizar_hud()


func _color_fallback(sym: String) -> Color:
	match sym:
		"K": return Color(0.3, 0.6, 1.0)
		"O": return Color(0.8, 0.2, 0.2)
		"C": return Color(0.9, 0.7, 0.1)
		"D": return Color(0.6, 0.4, 0.2)
		"L": return Color(1.0, 0.9, 0.0)
	return Color.WHITE


func _actualizar_hud():
	hp_bar.max_value = 3.0
	hp_bar.value     = GameState.player_hp
	hp_label.text    = "HP: %.1f / 3.0" % GameState.player_hp
	oro_label.text   = "Oro: %d" % GameState.player_oro
	llave_label.text = "🗝 Llave" if GameState.player_llave else "Sin llave"
	llave_label.modulate = Color.YELLOW if GameState.player_llave else Color.GRAY


# ═══════════════════════════════════════════════════════════
#  LOG DE MENSAJES
# ═══════════════════════════════════════════════════════════

func _on_message(text: String, color: String):
	log_text.append_text("[color=%s]%s[/color]\n" % [color, text])
	await get_tree().process_frame
	var sb = log_text.get_parent()  # ScrollContainer
	sb.scroll_vertical = sb.get_v_scroll_bar().max_value


func _log_bienvenida():
	_on_message("╔══════════════════════════════════╗", "#888888")
	_on_message("║   DUNGEON KNIGHT · Grilla 7×7    ║", "#aaccff")
	_on_message("╚══════════════════════════════════╝", "#888888")
	_on_message("Objetivo: recogé la llave y cruzá la puerta.", "#ffffff")
	_on_message("Comandos: 've arriba', 'ir al orco', 'abrir derecha', 'esperar'", "#aaaaaa")
	_on_message("Ollama debe estar corriendo en localhost:11434", "#666666")


# ═══════════════════════════════════════════════════════════
#  ENTRADA DE COMANDOS
# ═══════════════════════════════════════════════════════════

func _on_enviar():
	if LLMBridge._pendiente:
		return

	var texto = cmd_input.text.strip_edges()
	cmd_input.clear()

	if texto == "":
		return

	# Comandos locales
	if texto.to_lower() in ["ayuda", "help", "?"]:
		_log_bienvenida()
		return

	if texto.to_lower() in ["salir", "exit", "quit"]:
		get_tree().quit()
		return

	if GameState.nivel_terminado:
		return

	_on_message("» " + texto, "#cccccc")
	_on_message("  Interpretando…", "#666666")

	if GameState.en_combate:
		LLMBridge.interpretar_combate(texto)
	else:
		LLMBridge.interpretar_mapa(texto)


# ═══════════════════════════════════════════════════════════
#  RESPUESTA DEL LLM
# ═══════════════════════════════════════════════════════════

func _on_llm_respuesta(data: Dictionary):
	cmd_input.grab_focus()

	if GameState.en_combate:
		GameState.ejecutar_accion_combate(data)
	else:
		var consumido = GameState.ejecutar_accion(data)
		if consumido and not GameState.nivel_terminado and not GameState.en_combate:
			GameState.post_turno_jugador()


func _on_llm_error(msg: String):
	_on_message(msg, "#ff4444")
	cmd_input.grab_focus()


func _on_thinking(thinking: bool):
	thinking_label.visible = thinking
	cmd_input.editable = not thinking
	send_btn.disabled  = thinking


# ═══════════════════════════════════════════════════════════
#  COMBATE OVERLAY
# ═══════════════════════════════════════════════════════════

func _on_combat_started(orco_idx: int):
	var orco = GameState._get_orco_by_idx(orco_idx)
	if orco == null:
		return

	combat_panel.show()
	combat_orco_hp.max_value = 2.0
	combat_orco_hp.value     = orco.hp
	combat_orco_label.text   = "Orco %d  HP: %.1f / 2.0" % [orco.idx, orco.hp]
	combat_log.text          = "⚔ Escribe: atacar  o  defensa"


func _on_combat_ended():
	combat_panel.hide()
	_on_message("✔ Combate terminado. ¡Orco derrotado!", "#44ff88")


# ═══════════════════════════════════════════════════════════
#  GAME OVER
# ═══════════════════════════════════════════════════════════

func _on_game_over(es_victoria: bool):
	combat_panel.hide()
	game_over_panel.show()
	if es_victoria:
		game_over_label.text = "★ ¡NIVEL COMPLETADO!\nOro: %d" % GameState.player_oro
		game_over_label.modulate = Color(0.3, 1.0, 0.5)
	else:
		game_over_label.text = "☠ GAME OVER"
		game_over_label.modulate = Color(1.0, 0.3, 0.3)


func _reiniciar():
	game_over_panel.hide()
	combat_panel.hide()
	log_text.clear()
	GameState.cargar_nivel()
	_construir_grid()
	_on_board_changed()
	_log_bienvenida()
