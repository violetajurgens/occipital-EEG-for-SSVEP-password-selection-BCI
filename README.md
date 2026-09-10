# Single-channel occipital EEG for a calculator BCI based on steady-state visual evoked potentials (SSVEP)

## Required components and downloads

* **EXG Pill by Upside Down Labs**. An instrumentation amplifier designed for recording small biopotential signals such as EEG, EMG, and ECG.

* **Arduino / Raspberry Pi / compatible microcontroller board**. Used to acquire the analog EEG signal from the EXG Pill and transmit the data to the computer.

* **EEG electrodes**. Gel electrodes positioned over the occipital region. In this project, O1 and O2 are used for the single differential EEG channel.

* **PsychoPy**. PsychoPy. This is used to generate precisely timed visual stimuli flickering at different frequencies, with each frequency corresponding to a different BCI command. The PsychoPy script also sends stimulus markers through Lab Streaming Layer (LSL), allowing MATLAB to synchronize the EEG with the presented frequencies during calibration and calculator use.

# Electrode placement

Electrode placement followed the international 10–20 system, with the recording electrode positioned at O1 or O2 over the occipital region. The approximate electrode locations can be seen in the figure below left (Malmivuo & Plonsey, 1995). The reference electrode was placed over the mastoid process behind the ear. In my setup, adhesive electrodes were easier and more stable to use than dry metal electrodes with conductive gel. Maintaining good skin contact is important, as poor electrode contact can introduce artifacts that may resemble genuine EEG activity and lead to misleading results.

<img width="500" height="260" alt="Screenshot 2026-09-10 185955" src="https://github.com/user-attachments/assets/46327836-8d41-4668-891e-65516f1de4aa" />


**Reference**

Malmivuo, J., & Plonsey, R. (1995). *Bioelectromagnetism: Principles and applications of bioelectric and biomagnetic fields*. Oxford University Press.
