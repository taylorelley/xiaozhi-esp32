# Acoustic Test
This GUI is used to test audio received via `udp` from a LittleWise device. It converts incoming `pcm` into time/frequency-domain views, and can save the windowed sound. It is useful for identifying noise frequency distribution and measuring the accuracy of ASCII data transmitted over sound.

To run the firmware test, enable `USE_AUDIO_DEBUGGER` and set `AUDIO_DEBUG_UDP_SERVER` to the local machine's address.
Acoustic `demod` can be driven by `sonic_wifi_config.html` or by uploading to `PinMe` at the [LittleWise Sonic Wi-Fi Setup](https://iqf7jnhi.pinit.eth.limo) page.

# Acoustic Decode Test Log

> `v` means decoding succeeds when raw PCM is received directly on I2S DIN. `~` means noise reduction or extra tweaking is required for stable decoding. `X` means the result is poor even after noise reduction (may decode partially but very unstably).
> Some ADCs need finer noise-reduction tuning in the I2C configuration stage. Because such adjustments are device-specific, only the configs provided by the boards were tested.

| Device | ADC | MIC | Result | Notes |
| ---- | ---- | --- | --- | ---- |
| bread-compact | INMP441 | Integrated MEMS MIC | v |
| atk-dnesp32s3-box | ES8311 | | v |
| magiclick-2p5 | ES8311 | | v |
| lichuang-dev  | ES7210 | | ~ | INPUT_REFERENCE must be disabled during testing
| kevin-box-2 | ES7210 | | ~ | INPUT_REFERENCE must be disabled during testing
| m5stack-core-s3 | ES7210 | | ~ | INPUT_REFERENCE must be disabled during testing
| xmini-c3 | ES8311 | | ~ | Requires noise reduction
| atoms3r-echo-base | ES8311 | | ~ | Requires noise reduction
| atk-dnesp32s3-box0 | ES8311 | | X | Can receive and decode, but packet loss is very high
| movecall-moji-esp32s3 | ES8311 | | X | Can receive and decode, but packet loss is very high
