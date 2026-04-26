# Autum-Of-Code-2026-Tema-2

Sistema de interpretación de lenguaje natural para videojuegos basado en IA neuro-simbólica. Convierte instrucciones del usuario en acciones ejecutables mediante LLMs (Ollama) y validación simbólica estructurada.

Un juego de rol por turnos en grilla 7×7 controlado completamente por lenguaje natural. Escribís tus órdenes como si le hablaras a alguien, y un modelo de lenguaje (LLM) corriendo localmente las interpreta y las convierte en acciones dentro del calabozo.
Este proyecto es un prototipo de sistema neuro-simbólico: el componente neuronal (Ollama + Mistral/llama3/phi) entiende el lenguaje, y el componente simbólico (Python) valida y ejecuta las acciones sobre un estado explícito del juego.

# Objetivo del nivel

Encontrá al orco que porta la llave y derrotalo en combate
Usá la llave para abrir la puerta (abrir <dirección>)
Movete hacia la puerta para escapar del calabozo


# El tablero
Cada nivel es una grilla cuadrada de 7×7 generada aleatoriamente con:
SímboloEntidadDetallesKCaballero (vos)HP 3.0, empieza sin llave ni oroOOrcoHP 1 o 2, uno siempre porta la llaveCCofreAl abrirlo ganás 1 de oroDPuertaEn el borde del mapa, bloqueada hasta tener la llave.VacíoCelda transitable

# Comandos disponibles
El juego acepta lenguaje natural. No hay comandos exactos que memorizar.
Movimiento
ir 2 arriba
ve 3 a la derecha y luego 1 abajo
muévete hacia el orco
ir al cofre más cercano
ve a la puerta
Interacción
abrir derecha        → abre el cofre o la puerta en esa dirección
esperar              → pasa el turno sin hacer nada
Combate (en el mapa)
atacar izquierda     → inicia combate contra el orco adyacente
Combate (en la pantalla de pelea)
atacar / golpear / pegar
defenderse / guardia / escudo
huir / escapar / retroceder

# Sistema de combate
Cuando el caballero o un orco entran en contacto, se abre automáticamente una pantalla de combate por turnos.

Quien inició el contacto tiene prioridad de ataque en el primer turno
Un ataque hace 1.0 de daño; si el jugador se defendió ese turno, recibe solo 0.5
Al derrotar al orco que tiene la llave, esta pasa automáticamente al inventario
Si el HP del caballero llega a 0, el nivel termina en derrota
Los orcos hacen una sola acción por turno: o se mueven, o atacan, nunca ambas


# Requisitos

Python 3.12+
Ollama corriendo localmente (ollama serve)
Al menos un modelo instalado. Probados:

Modelo      Comando de instalación
Mistral      ollama pull mistral
Llama3       ollama pull llama3
Phi          ollama pull phi

# Instalación y uso
bash# 1. Clonar el repositorio
git clone https://github.com/Elias-Roman/Autum-Of-Code-2026-Tema-2.git

# 2. Instalar dependencias de Python
pip install requests

# 3. Instalar e iniciar Ollama (y modelos)
curl -fsSL https://ollama.com/install.sh | sh
ollama serve
# 3.1 Instalacion de modelos de IA para Ollama
ollama pull llama3
ollama pull phi3
ollama pull mistral

# 4. Configurar el modelo en Dungeon.py (línea ~14)
OLLAMA_MODEL = "mistral"   # o "llama3", "phi", etc.

# 5. Ejecutar el juego
python3 Dungeon.py
Al iniciar, el juego verifica automáticamente que Ollama esté corriendo y que el modelo configurado esté instalado. Si algo falla, te dice exactamente qué hacer.
El LLM nunca accede al estado del juego. Solo convierte texto a JSON. Toda la lógica, validación y ejecución vive en Python.

# Decisiones de diseño relevantes
Sin fallback de reglas. Si el modelo no responde o devuelve un JSON inválido, el turno se cancela y el estado del juego no cambia. El LLM es un componente obligatorio, no opcional. Esto es intencional: el objetivo del proyecto es estudiar el comportamiento del modelo como intérprete.
Medición de latencia. Cada llamada al LLM imprime el tiempo de respuesta en milisegundos. Esto permite comparar el rendimiento entre modelos (Mistral, LLaMA 3, Phi) para la documentación del proyecto.
Separación neuro-simbólica estricta. El modelo interpreta; Python valida y ejecuta. Ninguna función del motor recibe texto en lenguaje natural directamente.

# Autores
Juanjo Bai

Elias Román
