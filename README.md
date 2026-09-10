# Single-channel occipital EEG for a calculator BCI based on steady-state visual evoked potentials (SSVEP)

## Required components and downloads

* **EXG Pill by Upside Down Labs**. An instrumentation amplifier designed for recording small biopotential signals such as EEG, EMG, and ECG.

* **Arduino / Raspberry Pi / compatible microcontroller board**. Used to acquire the analog EEG signal from the EXG Pill and transmit the data to the computer.

* **EEG electrodes**. Gel electrodes positioned over the occipital region. In this project, O1 and O2 are used for the single differential EEG channel.

* **PsychoPy**. PsychoPy. This is used to generate precisely timed visual stimuli flickering at different frequencies, with each frequency corresponding to a different BCI command. The PsychoPy script also sends stimulus markers through Lab Streaming Layer (LSL), allowing MATLAB to synchronize the EEG with the presented frequencies during calibration and calculator use.
