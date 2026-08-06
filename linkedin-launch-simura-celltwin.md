Today I'm launching Simura — an open-source studio for digital-twin software — and its first project: CellTwin, a physics-based digital twin for battery energy storage systems (BESS) that turns a real battery pack into a fully controllable clone on your laptop, complete with the fault behavior and analytics a battery engineer would otherwise need a lab to study.

The result: prototyping battery diagnostics and safety analytics goes from a six-figure test rack and weeks of lab access, to a free download and 1–5 minutes.

Why it matters: battery health and safety — state-of-charge, state-of-health, and thermal-runaway early warning — is one of the most valuable problems in energy today, worth real money and capable of preventing real fires. But you can't learn or prototype on a live 1 MWh rack. So engineers are blocked from experimenting on exactly the systems that matter most. CellTwin removes the hardware.

What's new:
⭐️ Hardware-grade fidelity: models a battery from a single cell to a full rack with real electro-thermal dynamics and cell-to-cell imbalance — then lets you inject faults (internal shorts, cooling loss, thermal runaway) and watch the stack catch them.
⭐️ Fast, unsupervised intelligence: peer-consensus anomaly detection flags an internal short as critical at ~36°C — about 5 minutes before the cell hits its 45°C limit — then names the fault with state-of-health, time-to-critical, and a plain-English rationale. No training data.
⭐️ Real-hardware connectors: Modbus, OPC-UA, and MQTT bring live BMS data through the same twin, analytics, and dashboard unchanged.

This is also the fourth build in my one-app-a-month challenge — the one that turned a personal challenge into a company. Simura's idea is simple: faithful, fully controllable virtual systems that anyone can build diagnostics, dashboards, and ML on top of, all in the open — energy first, then manufacturing, mobility, and beyond.

Get started today:
🔧 Clone and run: `docker compose up` brings up the broker, time-series store, twin core, live dashboard, and a simulated faulted pack together.
🌐 GitHub: Apache-2.0 and contributor-friendly, with good first issues ready → [GitHub link]

If you work in batteries, energy storage, or digital twins — or you just like hard simulation problems — I'd love your help building this in the open. What industry should get a digital twin next?

#OpenSource #DigitalTwin #EnergyStorage #BESS #BatteryTech #BuildInPublic #Simura #Celltwin
