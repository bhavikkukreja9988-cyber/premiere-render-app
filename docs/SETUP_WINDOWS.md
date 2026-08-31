# Windows setup and troubleshooting — Remote V3

Remote V3 is an internet-connected Supabase design. The Sender and Render Station can be on different networks. Do not configure router port forwarding and do not expose the old LAN TCP/UDP ports to the internet.

## Render Station PC — first setup

1. Install and open FileSender.
2. Sign in with the application's **username + password**.
3. Select **Render Station** (or **Both**) when asked.
4. Choose the local workspace for received Premiere projects.
5. Give the station a clear name, for example `Bhavik Render PC`.
6. Enable or disable **Accept incoming jobs automatically**.
7. Configure retention if desired.
8. In FileSender, install the Media Encoder agent.
9. Restart Adobe Media Encoder.
10. In Media Encoder, enable **Allow Scripts to Write Files and Access Network** under Preferences → General.

When FileSender is open, the station automatically registers/heartbeats with Supabase and is shown as **Online** to authorized Senders.

There is no **Go Online** or **Go Offline** button.

Closing FileSender stops its remote worker/heartbeat and the station becomes offline. No hidden FileSender service should remain running.

The local IP address may be shown as informational/debug information, but it is not used by the remote Sender connection.

## Sender PC — first setup

1. Install and open FileSender.
2. Sign in with the same family username/password, or with an authorized account according to the application's sharing model.
3. Open **Send a project**.
4. Select the desired online Render Station by name.
5. Drag a `.prproj` file or Premiere project folder into the drop area.
6. Configure output/preset as needed.
7. Send the job.

The Sender must not ask for an IP address, TCP port, or pairing code during normal use.

## Offline behavior

If the selected Render Station is offline, **Send must be disabled**.

If the station goes offline after a job has been created/uploaded, the job must remain recoverable in Supabase and resume when the station is back online.

## Media Encoder

The render station uses the existing Media Encoder/ExtendScript pipeline. Media Encoder should launch minimized/below-normal priority without stealing focus.

Verify the installation with the project's check command where supported:

```powershell
python -m src.main --check
```

## Project media

Premiere projects that reference media outside the selected transfer folder may open with offline media on the Render Station. The application should warn about externally referenced media before transfer.

Using Premiere's File → Collect Files / Project Manager can help create a self-contained project folder before sending.

## Legacy LAN troubleshooting

The old `src/network/` implementation and TCP/UDP discovery are legacy migration code. Do not use them for Remote V3 troubleshooting and do not expose their ports to the public internet.

## Remote troubleshooting

**Render Station does not appear online.**

Check that FileSender is open, the correct user is signed in, the Supabase project configuration is present, and the station heartbeat is reaching Supabase.

**Send is disabled.**

Check that a valid project is selected, the user is signed in, and the chosen Render Station is shown as Online.

**Authentication failed.**

Use the configured username/password. The normal UI does not use email or pairing codes.

**Large transfer stops.**

The remote transfer layer is designed to resume using chunked/resumable Storage transfer. Do not restart by manually copying files unless the application explicitly reports a non-recoverable job.

**Job is queued but not rendering.**

Check the Render Station's Media Encoder status and agent installation. The station must be open and online.
