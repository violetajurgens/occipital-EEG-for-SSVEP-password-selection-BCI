# Single-channel occipital EEG for a calculator BCI based on steady-state visual evoked potentials (SSVEP)

## Required components and downloads

* **EXG Pill by Upside Down Labs**. An instrumentation amplifier designed for recording small biopotential signals such as EEG, EMG, and ECG.

* **Arduino / Raspberry Pi / compatible microcontroller board**. Used to acquire the analog EEG signal from the EXG Pill and transmit the data to the computer.

* **EEG electrodes**. Gel electrodes positioned over the occipital region. In this project, O1 and O2 are used for the single differential EEG channel.

* **GStreamer**. Required on Windows for Psychtoolbox `Screen()` functionality, which is used in MATLAB to generate the flickering visual SSVEP stimulus.
