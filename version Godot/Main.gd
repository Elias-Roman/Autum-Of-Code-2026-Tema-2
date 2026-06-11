extends Control

# ═══════════════════════════════════════════════════════════
#  Main.gd  v4  — Godot 4.6
#  Sistema de dos capas: BG (piso) + FG (entidades)
#  Tiles individuales desde kenney_tiny_dungeon/Tiles/
# ═══════════════════════════════════════════════════════════

@onready var grid_container : GridContainer  = $MarginContainer/HBox/LeftPanel/GridContainer
@onready var cmd_input       : LineEdit       = $MarginContainer/HBox/RightPanel/VBox/CmdInput
@onready var log_text        : RichTextLabel  = $MarginContainer/HBox/RightPanel/VBox/LogScroll/LogText
@onready var hp_bar          : ProgressBar    = $MarginContainer/HBox/RightPanel/VBox/HUD/HPBar
@onready var hp_label        : Label          = $MarginContainer/HBox/RightPanel/VBox/HUD/HPLabel
@onready var oro_label       : Label          = $MarginContainer/HBox/RightPanel/VBox/HUD/OroLabel
@onready var llave_label     : Label          = $MarginContainer/HBox/RightPanel/VBox/HUD/LlaveLabel
@onready var send_btn        : Button         = $MarginContainer/HBox/RightPanel/VBox/SendBtn
@onready var thinking_label  : Label          = $MarginContainer/HBox/RightPanel/VBox/ThinkingLabel
@onready var combat_panel    : PanelContainer = $MarginContainer/HBox/RightPanel/VBox/CombatPanel
@onready var combat_orco_hp  : ProgressBar    = $MarginContainer/HBox/RightPanel/VBox/CombatPanel/VBox/OrcoHPBar
@onready var combat_orco_lbl : Label          = $MarginContainer/HBox/RightPanel/VBox/CombatPanel/VBox/OrcoHPLabel
@onready var combat_hint     : Label          = $MarginContainer/HBox/RightPanel/VBox/CombatPanel/VBox/CombatHint
@onready var game_over_panel : PanelContainer = $GameOverPanel
@onready var game_over_label : Label          = $GameOverPanel/VBox/ResultLabel
@onready var restart_btn     : Button         = $GameOverPanel/VBox/RestartBtn

const TILE_SIZE := 64          # tamaño visual en pantalla (px)
const TILES_DIR := "res://kenney_tiny-dungeon/Tiles/"

# ── Mapa símbolo → nombre de archivo en Tiles/ ────────────
# "" = invisible (celda vacía encima del piso)
const SYMBOL_TO_FILE : Dictionary = {
	"."       : "tile_0000.png",   # piso vacío (fondo)
	"K"       : "tile_0096.png",   # caballero
	"K_DEAD"  : "tile_0121.png",   # caballero muerto
	"O"       : "tile_0109.png",   # orco
	"C"       : "tile_0089.png",   # cofre cerrado
	"C_OPEN"  : "tile_0091.png",   # cofre abierto
	"D"       : "tile_0045.png",   # puerta cerrada
	"D_OPEN"  : "tile_0033.png",   # puerta abierta
	"L"       : "tile_0101.png",   # llave
}

# Colores fallback si no carga el tile
const FALLBACK_COLORS : Dictionary = {
	"."      : Color(0.18, 0.18, 0.22),
	"K"      : Color(0.25, 0.55, 1.00),
	"K_DEAD" : Color(0.35, 0.35, 0.45),
	"O"      : Color(0.85, 0.22, 0.22),
	"C"      : Color(0.90, 0.65, 0.10),
	"C_OPEN" : Color(0.60, 0.45, 0.05),
	"D"      : Color(0.55, 0.35, 0.15),
	"D_OPEN" : Color(0.30, 0.20, 0.08),
	"L"      : Color(1.00, 0.92, 0.10),
}

var textures   : Dictionary = {}   # símbolo → Texture2D (o null)
var cell_nodes : Array      = []   # Array[Array] de {bg:ColorRect, fg:TextureRect}


func _ready():
	GameState.board_changed.connect(_on_board_changed)
	GameState.message_posted.connect(_on_message)
	GameState.combat_started.connect(_on_combat_started)
	GameState.combat_ended.connect(_on_combat_ended)
	GameState.game_over.connect(_on_game_over)
	GameState.llm_thinking.connect(_on_thinking)
	LLMBridge.respuesta_lista.connect(_on_llm_respuesta)
	LLMBridge.error_llm.connect(_on_llm_error)
	LLMBridge.ollama_status.connect(_on_ollama_status)

	_cargar_texturas()
	_construir_grid()

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
	var loaded := 0
	var missing := []
	for sym in SYMBOL_TO_FILE:
		var path = TILES_DIR + SYMBOL_TO_FILE[sym]
		if ResourceLoader.exists(path):
			textures[sym] = load(path)
			loaded += 1
		else:
			textures[sym] = null
			missing.append(SYMBOL_TO_FILE[sym])

	if loaded > 0:
		print("Texturas cargadas: %d/%d desde %s" % [loaded, SYMBOL_TO_FILE.size(), TILES_DIR])
	if missing.size() > 0:
		push_warning("Tiles no encontrados (fallback color): " + ", ".join(missing))


# ═══════════════════════════════════════════════════════════
#  CONSTRUCCIÓN DE GRILLA  (dos capas por celda)
# ═══════════════════════════════════════════════════════════

func _construir_grid():
	for ch in grid_container.get_children():
		ch.queue_free()
	cell_nodes = []
	grid_container.columns = GameState.SIZE

	for r in GameState.SIZE:
		var row := []
		for c in GameState.SIZE:
			# Panel respeta custom_minimum_size dentro de GridContainer
			var cell := Panel.new()
			cell.custom_minimum_size = Vector2(TILE_SIZE, TILE_SIZE)
			# Quitar el estilo por defecto del Panel para que no dibuje borde
			var empty_style := StyleBoxEmpty.new()
			cell.add_theme_stylebox_override("panel", empty_style)

			# ── Capa BG: ColorRect de piso siempre visible ───
			var bg_color := ColorRect.new()
			bg_color.name = "BGColor"
			bg_color.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
			bg_color.color = FALLBACK_COLORS["."]
			cell.add_child(bg_color)

			# ── Capa 2: textura piso ──────────────────────────
			var bg := TextureRect.new()
			bg.name         = "BG"
			bg.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
			bg.expand_mode  = TextureRect.EXPAND_IGNORE_SIZE
			bg.stretch_mode = TextureRect.STRETCH_SCALE
			bg.texture      = textures.get(".", null)
			cell.add_child(bg)

			# ── Capa 3: objeto fijo (puerta, cofre, llave) ───
			var obj_rect := TextureRect.new()
			obj_rect.name         = "ObjRect"
			obj_rect.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
			obj_rect.expand_mode  = TextureRect.EXPAND_IGNORE_SIZE
			obj_rect.stretch_mode = TextureRect.STRETCH_SCALE
			obj_rect.texture      = null
			cell.add_child(obj_rect)

			# ── Capa 4: personaje móvil ───────────────────────
			var fg := TextureRect.new()
			fg.name         = "FG"
			fg.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
			fg.expand_mode  = TextureRect.EXPAND_IGNORE_SIZE
			fg.stretch_mode = TextureRect.STRETCH_SCALE
			fg.texture      = null
			cell.add_child(fg)

			# ── Label fallback centrado ───────────────────────
			var lbl := Label.new()
			lbl.name = "FallbackLabel"
			lbl.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
			lbl.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
			lbl.vertical_alignment   = VERTICAL_ALIGNMENT_CENTER
			lbl.add_theme_font_size_override("font_size", 20)
			lbl.modulate = Color.WHITE
			lbl.visible  = false
			cell.add_child(lbl)

			grid_container.add_child(cell)
			row.append({"bg": bg, "obj_rect": obj_rect, "fg": fg, "lbl": lbl,
						"bg_color": bg_color, "cell": cell})
		cell_nodes.append(row)


# ═══════════════════════════════════════════════════════════
#  ACTUALIZAR TABLERO
# ═══════════════════════════════════════════════════════════

func _on_board_changed():
	for r in GameState.SIZE:
		for c in GameState.SIZE:
			var nodes    = cell_nodes[r][c]
			var bg       : TextureRect = nodes["bg"]
			var obj_rect : TextureRect = nodes["obj_rect"]
			var fg       : TextureRect = nodes["fg"]
			var lbl      : Label       = nodes["lbl"]
			var bg_color : ColorRect   = nodes["bg_color"]

			var obj_sym : String = GameState.board_obj[r][c]
			var fg_sym  : String = GameState.board_fg[r][c]

			# ── Capa 1: ColorRect de piso (siempre gris oscuro) ──
			bg_color.color = FALLBACK_COLORS["."]

			# ── Capa 2: textura de piso ──────────────────────
			var piso_tex = textures.get(".", null)
			bg.texture  = piso_tex
			bg.modulate = Color.WHITE

			# ── Capa 3: objeto fijo (puerta, cofre, llave) ───
			if obj_sym == "":
				obj_rect.texture  = null
				obj_rect.modulate = Color.TRANSPARENT
			else:
				var obj_tex = textures.get(obj_sym, null)
				if obj_tex != null:
					obj_rect.texture  = obj_tex
					obj_rect.modulate = Color.WHITE
				else:
					obj_rect.texture   = null
					obj_rect.modulate  = Color.TRANSPARENT
					bg_color.color     = FALLBACK_COLORS.get(obj_sym, Color.MAGENTA)

			# ── Capa 4: personaje móvil (K, O, K_DEAD) ───────
			if fg_sym == "":
				fg.texture  = null
				fg.modulate = Color.TRANSPARENT
				lbl.visible = false
			else:
				var fg_tex = textures.get(fg_sym, null)
				if fg_tex != null:
					fg.texture  = fg_tex
					fg.modulate = Color.WHITE
					lbl.visible = false
				else:
					fg.texture  = null
					fg.modulate = Color.TRANSPARENT
					lbl.text    = _sym_label(fg_sym)
					lbl.add_theme_color_override("font_color", Color.WHITE)
					bg_color.color = FALLBACK_COLORS.get(fg_sym, Color.MAGENTA)
					lbl.visible    = true

	_actualizar_hud()


func _sym_label(sym: String) -> String:
	match sym:
		"K": return "K"
		"K_DEAD": return "†"
		"O": return "O"
		"C": return "C"
		"C_OPEN": return "c"
		"D": return "D"
		"D_OPEN": return "d"
		"L": return "L"
	return "?"


# ═══════════════════════════════════════════════════════════
#  HUD
# ═══════════════════════════════════════════════════════════

func _actualizar_hud():
	hp_bar.max_value  = 3.0
	hp_bar.value      = GameState.player_hp
	hp_label.text     = "HP: %.1f / 3.0" % GameState.player_hp
	oro_label.text    = "Oro: %d" % GameState.player_oro
	llave_label.text  = "🗝 Llave" if GameState.player_llave else "Sin llave"
	llave_label.modulate = Color.YELLOW if GameState.player_llave else Color.GRAY


# ═══════════════════════════════════════════════════════════
#  LOG
# ═══════════════════════════════════════════════════════════

func _on_message(text: String, color: String):
	log_text.append_text("[color=%s]%s[/color]\n" % [color, text])
	await get_tree().process_frame
	var sb : ScrollContainer = log_text.get_parent()
	sb.scroll_vertical = int(sb.get_v_scroll_bar().max_value)


func _log_bienvenida():
	_on_message("─────────────────────────────────", "#555555")
	_on_message("DUNGEON KNIGHT  7×7", "#aaccff")
	_on_message("Recogé la llave (L) y cruzá la puerta (D).", "#ffffff")
	_on_message("Ejs: ve arriba · ir al orco · abrir derecha · esperar", "#888888")
	_on_message("─────────────────────────────────", "#555555")
	_on_message("⏳ Verificando Ollama…", "#666666")


func _on_ollama_status(ok: bool, info: String):
	if ok:
		_on_message(info, "#44cc88")
	else:
		for linea in info.split("\n"):
			_on_message(linea, "#ff5555")
		_on_message("  El juego funciona con Ollama corriendo.", "#888888")


# ═══════════════════════════════════════════════════════════
#  ENTRADA
# ═══════════════════════════════════════════════════════════

func _on_enviar():
	if LLMBridge._pendiente:
		return
	var texto := cmd_input.text.strip_edges()
	cmd_input.clear()
	if texto == "": return
	if texto.to_lower() in ["ayuda", "help", "?"]:
		_log_bienvenida(); return
	if GameState.nivel_terminado: return

	_on_message("» " + texto, "#dddddd")

	if GameState.en_combate:
		LLMBridge.interpretar_combate(texto)
	else:
		LLMBridge.interpretar_mapa(texto)


# ═══════════════════════════════════════════════════════════
#  LLM CALLBACKS
# ═══════════════════════════════════════════════════════════

func _on_llm_respuesta(data: Dictionary):
	cmd_input.grab_focus()
	if GameState.en_combate:
		GameState.ejecutar_accion_combate(data)
	else:
		var consumido := GameState.ejecutar_accion(data)
		if consumido and not GameState.nivel_terminado and not GameState.en_combate:
			GameState.post_turno_jugador()


func _on_llm_error(msg: String):
	_on_message(msg, "#ff4444")
	cmd_input.grab_focus()


func _on_thinking(thinking: bool):
	thinking_label.visible = thinking
	cmd_input.editable     = not thinking
	send_btn.disabled      = thinking


# ═══════════════════════════════════════════════════════════
#  COMBATE
# ═══════════════════════════════════════════════════════════

func _on_combat_started(orco_idx: int):
	var orco = GameState._get_orco_by_idx(orco_idx)
	if orco == null: return
	combat_panel.show()
	combat_orco_hp.max_value = 2.0
	combat_orco_hp.value     = orco.hp
	combat_orco_lbl.text     = "Orco %d   HP: %.1f / 2.0" % [orco.idx, orco.hp]
	combat_hint.text         = "Elegí: ¿Golpear  o  Guardia?"


func _on_combat_ended():
	combat_panel.hide()
	_on_message("✔ ¡Orco derrotado!", "#44ff88")


# ═══════════════════════════════════════════════════════════
#  GAME OVER
# ═══════════════════════════════════════════════════════════

func _on_game_over(es_victoria: bool):
	combat_panel.hide()
	game_over_panel.show()
	if es_victoria:
		game_over_label.text     = "★ ¡NIVEL COMPLETADO!\nOro: %d" % GameState.player_oro
		game_over_label.modulate = Color(0.3, 1.0, 0.5)
	else:
		game_over_label.text     = "☠  GAME OVER"
		game_over_label.modulate = Color(1.0, 0.3, 0.3)


func _reiniciar():
	game_over_panel.hide()
	combat_panel.hide()
	log_text.clear()
	GameState.cargar_nivel()
	_construir_grid()
	_on_board_changed()
	_log_bienvenida()
