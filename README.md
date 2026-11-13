# ppe-serving

One small PPE detector (YOLOv8s, exported to ONNX at 320 pixels with 8-bit weights), taken out of the notebook and run the ways an employer would ask for. Each part is small, tested, and reports numbers measured on a stated machine.

| Part | What it is | Status |
|---|---|---|
| [`ros2/`](ros2/) | A ROS 2 Jazzy workspace: a C++ lifecycle node that runs the detector with ONNX Runtime, and a C++ node that turns repeated violations into a Nav2 NavigateToPose goal. Run in Gazebo with Nav2 and as a replay with tests. | In this repository |
| `service/` | A FastAPI and ONNX Runtime service with a checksum-verified model registry step, Docker, Prometheus and Grafana, a k6 load test and Kubernetes manifests. | Built, being added |
| [`cpp/`](cpp/) | A C++17 library and command-line tool for the same inference path on ONNX Runtime, with a parity test against Python (bit-identical on five sample images), sanitizer-clean tests and measured latency, cold-start and memory tables. | In this repository |

The same model runs in the browser at [zulfaqarhafez.com/work/ppe-compliance](https://zulfaqarhafez.com/work/ppe-compliance), where its measured accuracy and its failures are written up.

## Read this first

- **The model.** Trained by my teammates in a university course project with Ultralytics YOLOv8 (AGPL-3.0), on a CC BY 4.0 dataset. My part there was system architecture and full stack. The model file is not committed here; each part downloads it by URL and checks its SHA-256. See the NOTICE file in each part.
- **Authorship.** Built by Zulfaqar Hafez with Claude Code as the coding agent.
- **Limits.** Everything was measured on one 4 vCPU virtual machine with no GPU. Nothing here has run on real robot hardware or served real users. Each part's README states its own limits.
- **Licence.** Not chosen yet, so no licence is granted for the code in this repository.
