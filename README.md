# RAMMS-Sim

Robotic Assistive Mobility and Manipulation Simulation (RAMMS) - An Unreal Engine 5 based simulation environment for robotic assistive technologies.

<!-- markdown-toc start - Don't edit this section. Run M-x markdown-toc-refresh-toc -->
**Table of Contents**

- [RAMMS-Sim](#ramms-sim)
  - [Overview](#overview)
  - [Prerequisites](#prerequisites)
  - [Developing](#developing)
    - [Code style](#code-style)
  - [Installation](#installation)
  - [Example Environments](#example-environments)
  - [Current Functionality](#current-functionality)
    - [1. Mobile Robotic Base (MeBot) Simulation](#1-mobile-robotic-base-mebot-simulation)
    - [2. Accessible Van with Ramp](#2-accessible-van-with-ramp)
    - [3. Kinova Jaco Gen 3 Manipulator](#3-kinova-jaco-gen-3-manipulator)
  - [License](#license)
  - [Contributing](#contributing)
  - [Contact](#contact)

<!-- markdown-toc end -->

## Overview

RAMMS-Sim provides a high-fidelity simulation environment for developing and testing robotic assistive mobility and manipulation systems. Built on Unreal Engine 5, it offers realistic physics, rendering, and interaction capabilities for research and development in assistive robotics.

## Prerequisites

- Unreal Engine 5
- Git with Git LFS support
- Git LFS configured on your system

## Developing

If you want to contribute or customize the plugin, you can clone the repository
and set it up in your Unreal project. If you want to make changes to the code,
please follow the code style guidelines below.

### Code style

1. Ensure `clang-format` is installed
2. Ensure [pre-commit](https://pre-commit.com) is installed
3. Set up `pre-commit` for this repository:

  ``` console
  pre-commit install
  ```

This helps ensure that consistent code formatting is applied.

## Installation

This repository uses submodules for plugins and Git LFS for large assets. Clone recursively to ensure all dependencies are included:

```bash
git clone --recursive https://github.com/rammp-org/ramms-sim.git
```

If you've already cloned the repository without `--recursive`, initialize the submodules:

```bash
git submodule update --init --recursive
```

Ensure Git LFS is installed and configured to download all assets:

```bash
git lfs install
git lfs pull
```

## Example Environments

This repository does not include all example environments to keep the repository size manageable. Additional environments and assets can be downloaded and added to the project for free using the **Fab plugin** within Unreal Engine.

*[Screenshots showing how to use the Fab plugin will be added here]*

## Current Functionality

### 1. Mobile Robotic Base (MeBot) Simulation

Complete simulation of the MeBot mobile base with:
- Main drive wheels with independent control
- Front caster arm articulation and control
- Rear caster arm dampeners
- Rear caster arm and main drive wheel elevation system
- Main drive wheel translation for multiple drive modes:
  - Front wheel drive
  - Mid wheel drive
  - Rear wheel drive

### 2. Accessible Van with Ramp

Articulated accessible van system featuring:
- Controllable van door
- Articulated van ramp with realistic physics

**Credits:** This is a custom modification of CC-licensed base model: "Volkswagen ID. BUZZ" (https://skfb.ly/oTs6B) by Sloftm_Carz is licensed under Creative Commons Attribution (http://creativecommons.org/licenses/by/4.0/).

### 3. Kinova Jaco Gen 3 Manipulator

Robotic arm simulation with:
- Proper skeletal mesh setup
- Joint constraints configured
- *Note: Arm controller implementation is currently in progress*

## License

See LICENSE file for details.

## Contributing

Contributions are welcome! Please fork the repository and submit a pull request with your changes.

## Contact

For questions or support, please open an issue on GitHub or contact the maintainers directly.
