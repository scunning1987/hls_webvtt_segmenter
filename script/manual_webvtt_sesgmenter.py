import json
import logging
import datetime
import time
import boto3

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

def lambda_handler(event, context):

    function_start = datetime.datetime.now().strftime("%s")

    # Initialize S3 client
    s3 = boto3.client('s3')

    # Check the passed event for key : hls_manifest

    if 'hls_manifest' not in event:
        LOGGER.error("Event body passed to script is missing key - hls_manifest")
        raise Exception("Event body passed to script is missing key - hls_manifest")

    if "s3" not in event['hls_manifest']:
        LOGGER.error("You need to pass the s3:// uri for the index manifest of the HLS asset")
        raise Exception("You need to pass the s3:// uri for the index manifest of the HLS asset")

    bucket = event['hls_manifest'].split("/",3)[2]
    key = event['hls_manifest'].split("/",3)[3]
    master_base_key_path = key.rsplit("/",1)[0]
    master_key_path = key

    LOGGER.info("Master manifest location, bucket: %s , key: %s" % (bucket,master_key_path))

    # Do a check to see if HLS output group found, if not, exit the script with Warning but nicely
    if hls_output_not_found:
        LOGGER.warning("No HLS output group found, exiting script")
        LOGGER.warning("Received event from CloudWatch : %s " % (event))
        return 1

    # Get master manifest from S3, then parse to get location of vtt manifest
    ## Get manifest
    try:
        master_manifest_byte = s3.get_object(Bucket=bucket, Key=key)
    except Exception as e:
        LOGGER.error("Issue getting master manifest from S3, got exception: %s " % (e))
        raise Exception("Issue getting master manifest from S3, got exception: %s " % (e))

    master_manifest_text = master_manifest_byte['Body'].read().decode('utf-8')
    LOGGER.info("Master manifest body : %s " % (master_manifest_text))

    ## Parse manifest
    master_manifest_to_list = master_manifest_text.split("\n")

    ## iterate through manifest to get subtitle uri
    vtt_index_relative_url = ""
    vtt_index_relative_slashes = 1
    for line in master_manifest_to_list:
        if "#EXT-X-MEDIA:TYPE=SUBTITLES" in line:
            attributes = line.split(",")
            for attribute in attributes:
                if "URI" in attribute:
                    vtt_index_relative_url = attribute.split("\"")[1]

                    if vtt_index_relative_url.count("../") > 0:
                        vtt_index_relative_slashes += vtt_index_relative_url.count("../")
                        vtt_index_relative_url = vtt_index_relative_url.rsplit("/",1)[1]

    ## Challenge to check if subtitle m3u8 is referenced in the master manifest, if not, exit
    if vtt_index_relative_url == "":
        LOGGER.error("Unable to find webvtt manifest location specified in master manifest, here's the manifest : %s " % (master_manifest_text))
        raise Exception("ERROR : Unable to find webvtt manifest location specified in master manifest, here's the manifest : %s " % (master_manifest_text))

    # combine manifest base path and relative webvtt uri to create the s3 object url
    vtt_manifest_key =  "%s/%s" % (master_key_path.rsplit("/",vtt_index_relative_slashes)[0],vtt_index_relative_url)
    LOGGER.info("Got VTT Manifest key path, here it is : %s " % (vtt_manifest_key))

    # Get VTT manifest and location to VTT files and EXTINF Cumulative start times
    ## Get manifest
    try:
        vtt_manifest_byte = s3.get_object(Bucket=bucket, Key=vtt_manifest_key)
    except Exception as e:
        LOGGER.error("Issue getting vtt manifest from S3, got exception: %s " % (e))
        raise Exception("Issue getting vtt manifest from S3, got exception: %s " % (e))

    vtt_manifest_request = vtt_manifest_byte['Body'].read().decode('utf-8')
    LOGGER.debug("VTT manifest body : %s " % (vtt_manifest_request))


    ## Parse manifest
    vtt_manifest_to_list = vtt_manifest_request.split("#")

    ## Create dictionary to reference that has all the data needed to grab and concatenate the vtt files
    vtt_dict = dict()
    vtt_file_relative_slashes = 1
    cumulative_duration = 0
    vtt_index = 1
    for line in vtt_manifest_to_list:
        if "EXTINF" in line:
            duration = int(float(line.split(",")[0].split(":")[1]))

            vtt_file_url =  line.split(",")[1].replace("\n","")

            if vtt_file_url.count("../") > 0:
                vtt_file_relative_slashes += vtt_file_url.count("../")
                vtt_file_url = vtt_file_url.rsplit("/",1)[1]

            # combine manifest base path and relative uri to create the absolute url for the webvtt file(s)
            vtt_file_key =  "%s/%s" % (vtt_manifest_key.rsplit("/",vtt_file_relative_slashes)[0],vtt_file_url)

            vtt_dict[vtt_index] = {}
            vtt_dict[vtt_index]['vtt_file_bucket'] = bucket
            vtt_dict[vtt_index]['vtt_file_key'] = vtt_file_key
            vtt_dict[vtt_index]['duration'] = duration
            vtt_dict[vtt_index]['cumulative_duration'] = cumulative_duration

            ## Add the duration of this vtt file to the cumulative duration
            cumulative_duration += duration

            vtt_index += 1
    LOGGER.info("Dictionary to work from: %s " % (vtt_dict))

    ## vtt_dict

    # Iterate through VTT files and concatenate to make 1 large file
    concatenated_vtt_list = []
    vtt_head = ""
    test_vtt_list = []
    for vtt_index in vtt_dict:
        vtt_file_bucket = vtt_dict[vtt_index]['vtt_file_bucket']
        vtt_file_key = vtt_dict[vtt_index]['vtt_file_key']
        vtt_file_duration = vtt_dict[vtt_index]['duration']
        vtt_start_delta = vtt_dict[vtt_index]['cumulative_duration']

        ## Get vtt file
        try:
            vtt_file_byte = s3.get_object(Bucket=vtt_file_bucket, Key=vtt_file_key)
        except Exception as e:
            LOGGER.error("Issue getting vtt file from S3, got exception: %s " % (e))
            raise Exception("Issue getting vtt file from S3, got exception: %s " % (e))

        vtt_file_request = vtt_file_byte['Body'].read().decode('utf-8')
        LOGGER.debug("VTT file body : %s " % (vtt_manifest_request))

        vtt_file_list = vtt_file_request.split("\n\n")


        if vtt_head == "":
            vtt_head = vtt_file_list[0]
            concatenated_vtt_list.append(vtt_head)

        ## Remove vtt header from list before iterating through
        vtt_file_list.pop(0)

        ## Some VTT files have trailing new lines or malformed lines. The below loop removes them from the list before processing
        lines_to_delete = []
        for line in range(0,len(vtt_file_list)):
            if not vtt_file_list[line][0:2].isdigit():
                # this line is malformed or should be a part of the previous line
                vtt_file_list[line-1] = vtt_file_list[line-1] + "\n" + vtt_file_list[line]
                lines_to_delete.append(int(line))

        lines_to_delete.sort(reverse = True )
        for ltd in lines_to_delete:
            #return ltd
            vtt_file_list.pop(ltd)

        ## Change timing in VTT lines and add to concatenated VTT LIST
        for line_number in range(0,len(vtt_file_list)):

            start_time_str = vtt_file_list[line_number].split("-->")[0].replace(" ","") # "00:00:01.042"
            end_time_str = vtt_file_list[line_number].split("-->")[1].split(" ")[1].split("\n")[0]

            start_time_seconds = (int(start_time_str.split(":")[0]) * 3600) + (int(start_time_str.split(":")[1]) * 60) + float(start_time_str.split(":")[2])
            end_time_seconds = (int(end_time_str.split(":")[0]) * 3600) + (int(end_time_str.split(":")[1]) * 60) + float(end_time_str.split(":")[2])

            #new_start_time_str = str(datetime.timedelta(seconds=start_time_seconds+vtt_start_delta))
            #new_end_time_str = str(datetime.timedelta(seconds=end_time_seconds+vtt_start_delta))

            #concatenated_vtt_list.append(vtt_file_list[line_number].replace(start_time_str,new_start_time_str).replace(end_time_str,new_end_time_str) + "\n\n")
            concatenated_vtt_list.append(vtt_file_list[line_number] + "\n\n")

    # !!!!!!!!!!!!!!!!!
    '''
    line_number = 2
    
    start_time_str = concatenated_vtt_list[line_number].split("-->")[0].replace(" ","") # "00:00:01.042"
    end_time_str = concatenated_vtt_list[line_number].split("-->")[1].split(" ")[1].split("\n")[0]
    
    start_time_seconds = (int(start_time_str.split(":")[0]) * 3600) + (int(start_time_str.split(":")[1]) * 60) + float(start_time_str.split(":")[2])
    end_time_seconds = (int(end_time_str.split(":")[0]) * 3600) + (int(end_time_str.split(":")[1]) * 60) + float(end_time_str.split(":")[2])
    start_time_seconds = 30.500
    new_start_time_str = time.strftime('%H:%M:%S.%f', time.gmtime(int(start_time_seconds))) #[:-3]
    new_end_time_str = time.strftime('%H:%M:%S.%f', time.gmtime(int(end_time_seconds))) #[:-3]
    
    return {
        'start_time_str':start_time_str,
        'end_time_str':end_time_str,
        'start_time_seconds':start_time_seconds,
        'end_time_seconds':end_time_seconds,
        'new_start_time_str':new_start_time_str,
        'new_end_time_str':new_end_time_str
    }
    '''

    # !!!!!!!!!!!!!!!!!

    concatenated_vtt_str = ""
    for line in concatenated_vtt_str:
        concatenated_vtt_str = concatenated_vtt_str + line

    # Grab a Video rendition from the master manifest and copy the segment layout and cumulative start times (in case webvtt offset is needed)

    ## Parse manifest
    ## iterate through manifest to get video uri
    video_index_relative_url = ""
    video_index_relative_slashes = 1

    for line in range(0,len(master_manifest_to_list)):
        if "CODECS=\"avc1" in master_manifest_to_list[line]:
            if video_index_relative_url == "":
                video_index_relative_url = master_manifest_to_list[line+1]

                if video_index_relative_url.count("../") > 0:
                    video_index_relative_slashes += video_index_relative_url.count("../")
                    video_index_relative_url = video_index_relative_url.rsplit("/",1)[1]

    if video_index_relative_url == "":
        LOGGER.error("Couldn't parse master manifest and find video playlist that matched codec :avc, here is the master manifest : %s " % (master_manifest_text))
        raise Exception("ERROR : Couldn't parse master manifest and find video playlist that matched codec :avc, here is the master manifest : %s " % (master_manifest_text))

    ## Construct the Key path from the relative index path and master manifest key path
    video_manifest_key =  "%s/%s" % (master_key_path.rsplit("/",video_index_relative_slashes)[0],video_index_relative_url)
    LOGGER.info("Parsed master manifest for video playlist url: %s " % (video_manifest_key))


    # Get video manifest and store EXTINF segment lengths and Cumulative start times
    ## Get manifest

    ## Get vtt file
    try:
        video_manifest_byte = s3.get_object(Bucket=bucket, Key=video_manifest_key)
    except Exception as e:
        LOGGER.error("Issue getting video manifest from S3, got exception: %s " % (e))
        raise Exception("Issue getting video manifest from S3, got exception: %s " % (e))

    video_manifest_request = video_manifest_byte['Body'].read().decode('utf-8')
    LOGGER.debug("VTT file body : %s " % (video_manifest_request))

    ## Parse manifest
    video_manifest_to_list = video_manifest_request.split("#")

    ## Create dictionary to reference that has all the data needed to grab and concatenate the vtt files
    video_dict = dict()
    cumulative_duration = 0
    video_index = 1

    for line in video_manifest_to_list:
        if "EXTINF" in line:
            duration = int(float(line.split(",")[0].split(":")[1]))

            '''
            vtt_file_url =  line.split(",")[1].replace("\n","")

            if vtt_file_url.count("../") > 0:
                vtt_file_relative_slashes += vtt_file_url.count("../")
                vtt_file_url = vtt_file_url.rsplit("/",1)[1]
            
            # combine manifest base path and relative uri to create the absolute url for the webvtt file(s)
            vtt_file_absolute_url = vtt_manifest_url.rsplit("/",vtt_file_relative_slashes)[0] + "/%s" % (vtt_file_url)
            '''

            video_dict[video_index] = {}
            video_dict[video_index]['vtt_file_url'] = "segmented_vtt_%s.vtt" % (str(video_index).zfill(5))
            video_dict[video_index]['duration'] = duration
            video_dict[video_index]['cumulative_duration'] = cumulative_duration

            ## Add the duration of this segment file to the cumulative duration
            cumulative_duration += duration

            video_index += 1


    # Create template for new VTT manifest file (copying the video playlist but replacing relative paths to new vtt files)
    video_index = 1
    new_vtt_manifest_list = []
    for line in range(0,len(video_manifest_to_list)):

        newline = ""
        if "EXTINF" in video_manifest_to_list[line]:
            video_segment_url =  video_manifest_to_list[line].split(",")[1].replace("\n","")
            vtt_segment_url = video_dict[video_index]['vtt_file_url']
            newline = video_manifest_to_list[line].replace(video_segment_url,vtt_segment_url)
            video_index += 1
        else:
            newline = video_manifest_to_list[line]

        new_vtt_manifest_list.append(newline)

    new_vtt_manifest_str = '#'.join(new_vtt_manifest_list)

    # Now get the concatenated VTT list and create segments with relative timestamps for each vtt entry
    # iterate throughconcatenated_vtt_list our video_dict, then run through concatenated_vtt_list to find entries that fall within segment boundaries

    for vtt_segment in video_dict:
        vtt_segment_start = video_dict[vtt_segment]['cumulative_duration']
        vtt_segment_end = video_dict[vtt_segment]['duration'] + vtt_segment_start

        segmented_vtt_list = []
        segmented_vtt_list.clear()
        segmented_vtt_list.append(concatenated_vtt_list[0] + "\n\n")

        for line_number in range(1,len(concatenated_vtt_list)):

            start_time_str = concatenated_vtt_list[line_number].split("-->")[0].replace(" ","") # "00:00:01.042"
            end_time_str = concatenated_vtt_list[line_number].split("-->")[1].split(" ")[1].split("\n")[0]

            start_time_seconds = (int(start_time_str.split(":")[0]) * 3600) + (int(start_time_str.split(":")[1]) * 60) + float(start_time_str.split(":")[2])
            end_time_seconds = (int(end_time_str.split(":")[0]) * 3600) + (int(end_time_str.split(":")[1]) * 60) + float(end_time_str.split(":")[2])

            if start_time_seconds >= vtt_segment_start and start_time_seconds <= vtt_segment_end:
                #vtt_segment_start = 0
                new_start_time_str = str(datetime.timedelta(seconds=start_time_seconds-vtt_segment_start))
                new_end_time_str = str(datetime.timedelta(seconds=end_time_seconds-vtt_segment_start))
                #new_start_time_str = time.strftime('%H:%M:%S.%f', time.gmtime(int(start_time_seconds)))[:-3]
                #new_end_time_str = time.strftime('%H:%M:%S.%f', time.gmtime(int(end_time_seconds)))[:-3]

                #segmented_vtt_list.append(concatenated_vtt_list[line_number].replace(start_time_str,new_start_time_str).replace(end_time_str,new_end_time_str) + "\n\n")

                segmented_vtt_list.append(concatenated_vtt_list[line_number] + "\n\n")

        segmented_vtt_str = ""
        for line in segmented_vtt_list:
            segmented_vtt_str = segmented_vtt_str + line

        # PUT new VTT files to S3
        ## bucket is known
        ## key is = original vtt manifest base path + custom name 0000x.vtt
        new_vtt_key = "%s/%s" % (vtt_manifest_key.rsplit("/",vtt_file_relative_slashes)[0],video_dict[vtt_segment]['vtt_file_url'])
        try:
            LOGGER.info("Now writing new VTT file to S3 : %s" % (new_vtt_key))
            s3_put_response = s3.put_object(Body=segmented_vtt_str, Bucket=bucket, Key=new_vtt_key,ContentType='text/vtt',ACL='bucket-owner-full-control')
        except Exception as e:
            LOGGER.error("Unable to write new VTT File to S3, got exception : %s " % (e))
            raise Exception("Unable to write new VTT File to S3, got exception : %s " % (e))

    # Create new VTT Manifest file
    ## body = new_vtt_manifest_str
    ## key = vtt_manifest_key # overwriting original
    new_vtt_manifest_key = "%s/%s" % (vtt_manifest_key.rsplit("/",1)[0],"segmented_vtt.m3u8")
    try:
        LOGGER.info("Now writing new VTT manifest to S3 : %s" % (vtt_manifest_key))
        s3_put_response = s3.put_object(Body=new_vtt_manifest_str, Bucket=bucket, Key=new_vtt_manifest_key,ContentType='application/vnd.apple.mpegurl',ACL='bucket-owner-full-control')
    except Exception as e:
        LOGGER.error("Unable to write new VTT manifest to S3, got exception : %s " % (e))
        raise Exception("Unable to write new VTT manifest to S3, got exception : %s " % (e))

    # Create new master manifest referencing new VTT manifest file
    ## Create new master manifest replacing all references to old vtt manifest file
    new_master_manifest_list = []
    for line in master_manifest_to_list:

        newline = line.replace(vtt_index_relative_url,"segmented_vtt.m3u8")
        new_master_manifest_list.append(newline)

    new_master_manifest_str = '\n'.join(new_master_manifest_list)

    ## PUT new manifest file to S3
    new_master_manifest_key = master_key_path.replace(".m3u8","-new.m3u8")
    try:
        LOGGER.info("Now writing new master manifest to S3 : %s" % (vtt_manifest_key))
        s3_put_response = s3.put_object(Body=new_master_manifest_str, Bucket=bucket, Key=new_master_manifest_key,ContentType='application/vnd.apple.mpegurl',ACL='bucket-owner-full-control')
    except Exception as e:
        LOGGER.error("Unable to write new master manifest to S3, got exception : %s " % (e))
        raise Exception("Unable to write new master manifest to S3, got exception : %s " % (e))

    function_runtime = int(datetime.datetime.now().strftime("%s")) - int(function_start)


    return "Done - script took %s seconds to execute" % (str(function_runtime))