# Confirmed facts (user-verified). The drafting prompt includes this file verbatim.
# Only numbers that appear in this file may be quoted in a first email; any other
# metric (%, decimals, 4.5x, 10M ...) is stripped from drafts. Edit with care.

## High-energy physics / ML for physics (lead with this for HEP, ML, physics targets)
- GDS-ParT (Gated Dual-Stream Particle Transformer), built in Prof. Abhishek Iyer's HEP group at IIT Delhi (May-Jul 2026): pairwise kinematics gate the query/key channels of a Particle Transformer.
- Result: 84.84% accuracy and 0.9853 macro AUC on 1M JetClass test jets (10 classes).
- Trained 2.07M parameters on 10M JetClass training jets on a single 6 GB GPU; cut the per-jet cache from ~256 KB to ~1.9 KB with GPU pairwise features.
- Letter of Commendation from Prof. Abhishek Iyer for this work (2026).
- Code: github.com/Avinashistoocool/Gated-Dual-Stream-Particle-Transformer
- GDS-ParT-MoE (interpretability, preliminary): sparse-upcycled to an 8-expert, top-2 mixture of experts; layer-0 experts split particles by charge/species (NMI 0.45/0.43) and one expert showed 4.5x muon enrichment. Code: github.com/Avinashistoocool/GDS-parT-MoE

## Robotics / swarms / planning / control
- NIDAR rescue drone-swarm coverage (team lead, Team Asclepius, since Aug 2026): unified medial-axis, harmonic, fast-marching and lawnmower planners as arrival-time fields; a verify-repair loop gives 100% simulated coverage on 12-drone runs; exports ArduPilot missions over MAVLink. Code: github.com/Avinashistoocool/asclepius
- A* lunar-rover planner over a 6-term cost map with a 15-degree slope limit (ISRO Bharatiya Antariksh Hackathon 2026). Code: github.com/Avinashistoocool/ISRO-BAH-26

## Drones / flight software / reliability
- AnaTele: open-source investigation tool for ArduPilot flight logs (3D replay, phase inference, 20 declarative diagnostic rules, ranked failure hypotheses). Code: github.com/Avinashistoocool/AnaTele

## Computer vision / geometry / applied maths
- Colour-based object tracking in video with OpenCV (HSV masks, contours, convex hulls, centroid trajectories and speeds).
- Medial axis: derived the medial axis transform via Lagrangian mechanics and the Eikonal equation; extracted skeletons with distance transforms and Voronoi diagrams in NumPy/OpenCV.

## General
- Second-year B.Tech Engineering Physics student at IIT Delhi.
- GitHub: github.com/Avinashistoocool
