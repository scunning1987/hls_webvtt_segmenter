# HLS WebVTT Segmenter
## Overview
A script to run as a post transcode Lambda for MediaConvert jobs. The script will modify the WebVTT file segmentation to match video segments. This is to make the subtitle rendition compatible for downstream ad insertion components.

![](images/emc_webvtt_segmenter_architecture.png?width=60pc&classes=border,shadow)

1. MediaConvert outputs HLS to Amazon S3
2. MediaConvert sends a job completion event to Amazon CloudWatch
3. The CloudWatch event invokes an AWS Lambda function to run, the Lambda function pulls all necessary maniifest files and all WebVTT files from S3
4. The Lambda function then modifies the WebVTT renditions segmentation to match the video, then puts new manifest and WebVTT files to S3

### Prerequisites
* You need an AWS account
* Your IAM user must be able to set up CloudWatch events, create AWS Lambda functions, create IAM service roles, and full access to an S3 bucket
* It is assumed that MediaConvert is being used to trigger the script
* Download, or copy this Lambda [script](script/emc_webvtt_segmenter.py)

## Deployment Instructions
To deploy this solution you need to:
* Create an AWS Lambda function and IAM service role to give it relevant permissions
* Create an Amazon CloudWatch event to trigger on the completion of a MediaConvert transcode job

### AWS Lambda Function
1. Login to the AWS console
2. Navigate to the AWS Lambda service console
3. Select **Create function**
4. Give the function a name, for example: **emc_webvtt_segmenter**
5. For runtime, select: Python 3.8
6. Select **Create function**
7. In the code block section, paste the contents of the script copied/downloaded from above
8. Import the Zip!
9. Go to the Configuration tab, then General configuration. Select the **Edit** button and change the timeout value to 30 seconds and Save
10. Next, go to Permissions, under Execution role, select the Role hyperlink for the IAM role that was created with this Lambda function

*Note; this will open a new tab in your browser to the IAM Console...*

**For this exercise, we'll give the AWS Lambda function full access to your S3 bucket, as the function needs to READ the DASH manifest, as well as WRITE/PUT an updated manifest back to S3. The access can be further restricted with a tighter policy. See the [AWS policy generator](https://awspolicygen.s3.amazonaws.com/policygen.html) to build a more restricted policy**

11. In the role Summary, under the Permissions tab select **Add inline policy**
12. In the Create policy wizard, select the JSON tab, then paste the below contents into the code block. **Replace "mybucket" with the name of your S3 buckeet**
```
{
"Version": "2012-10-17",
"Statement": [
{
"Sid": "VisualEditor0",
"Effect": "Allow",
"Action": "s3:*",
"Resource": "arn:aws:s3:::mybucket"
}
]
}
```
13. Select the **Review policy** button, give the policy a name, ie. FullAccessToS3BucketX, then select the **Create policy** button
14. You can now close the IAM console tab

### CloudWatch Event
1. Login to your AWS account
2. Navigate to Amazon CloudWatch
3. Expand Events, then Select Rules, followed by the **Create rule** button
4. Under Event source, select **Event Pattern**, then **Build custom event pattern** from the drop-down menu
5. Copy the below json block and paste into the event pattern code block

```
{
  "source": ["aws.mediaconvert"],
  "detail-type": ["MediaConvert Job State Change"],
  "detail": {
    "status": ["COMPLETE"],
    "outputGroupDetails": {
      "type": ["HLS_GROUP"]
    }
  }
}
```

6. Under Targets, select **Add target**
7. Select **Lambda function** from the target drop-down menu
8. In the Function field, select your Lambda function from the drop-down menu
9. Select the **Configure details** button
10. Give the rule a name, ie. **MediaConvert Completion Event - DASH**, and optionally, a description to further identify the rule
11. Select the **Create rule** button

*Note: From this point on, any MediaConvert job completion events that match the event pattern above will trigger the rule to invoke your Lambda function*

Add your AWS Lambda function as a target of the event, give the event trigger a name and save!

## How To Use
The script will now run whenever a MediaConvert job completes and meets the event pattern specified in our CloudWatch event rule.

```
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:7
#EXT-X-MEDIA-SEQUENCE:1
#EXT-X-PLAYLIST-TYPE:VOD
#EXTINF:300,
indexvtt_00001.vtt
#EXTINF:301,
indexvtt_00002.vtt
#EXTINF:300,
indexvtt_00003.vtt
#EXTINF:300,
indexvtt_00004.vtt
#EXTINF:300,
indexvtt_00005.vtt
#EXTINF:301,
indexvtt_00006.vtt
#EXTINF:300,
indexvtt_00007.vtt
#EXTINF:300,
indexvtt_00008.vtt
#EXTINF:301,
indexvtt_00009.vtt
#EXTINF:300,
indexvtt_00010.vtt
```

The script downloads all vtt files and concatenates them, before segmenting them again to match the video renditions, then a new VTT manifest is written, like so:

```
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:7
#EXT-X-MEDIA-SEQUENCE:1
#EXT-X-PLAYLIST-TYPE:VOD
#EXTINF:6,
segmented_vtt_00001.vtt
#EXTINF:6,
segmented_vtt_00002.vtt
#EXTINF:6,
segmented_vtt_00003.vtt
#EXTINF:6,
segmented_vtt_00004.vtt
#EXTINF:6,
segmented_vtt_00005.vtt
#EXTINF:6,
segmented_vtt_00006.vtt
#EXTINF:6,
segmented_vtt_00007.vtt
#EXTINF:6,
segmented_vtt_00008.vtt
#EXTINF:6,
segmented_vtt_00009.vtt
#EXTINF:6,
segmented_vtt_00010.vtt
```

Finally, a new master manifest is written, containing the URI of the newly written WebVTT subtitle file. An example is below:

```
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-INDEPENDENT-SEGMENTS
#EXT-X-STREAM-INF:BANDWIDTH=6523574,AVERAGE-BANDWIDTH=2690724,CODECS="avc1.4d4028,mp4a.40.2",RESOLUTION=1920x1080,FRAME-RATE=29.970,SUBTITLES="subs"
index_1.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=3082182,AVERAGE-BANDWIDTH=1258595,CODECS="avc1.4d401f,mp4a.40.2",RESOLUTION=1280x720,FRAME-RATE=29.970,SUBTITLES="subs"
index_2.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=1450174,AVERAGE-BANDWIDTH=543970,CODECS="avc1.77.30,mp4a.40.2",RESOLUTION=640x360,FRAME-RATE=29.970,SUBTITLES="subs"
index_3.m3u8
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="English",DEFAULT=YES,AUTOSELECT=YES,FORCED=NO,LANGUAGE="eng",URI="segmented_vtt.m3u8"
```

The name of the new master manifest file contains a `-new` suffix, for example:
Original : index.m3u8
New : index-new.m3u8
